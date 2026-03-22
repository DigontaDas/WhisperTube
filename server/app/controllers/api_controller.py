from flask import Blueprint, request, jsonify
import logging
import os
import re
import tempfile
import shutil
import random

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__, url_prefix='/api')


def extract_video_id(url):
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def get_proxies_list():
    multi = os.environ.get('WEBSHARE_PROXIES', '')
    if multi:
        return [p.strip() for p in multi.split(',') if p.strip()]
    single = os.environ.get('WEBSHARE_PROXY', '')
    if single:
        return [single]
    return []


def get_youtube_transcript(video_id):
    """
    Fetch page AND caption using the SAME session/proxy in one go.
    The caption URL token is tied to the session that fetched the page.
    """
    import requests
    import json

    proxies_list = get_proxies_list()
    if not proxies_list:
        logger.warning("No proxies configured")
        return None

    random.shuffle(proxies_list)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Connection': 'keep-alive',
    }

    for proxy_url in proxies_list:
        proxies = {'http': proxy_url, 'https': proxy_url}
        try:
            # Use a persistent session — same cookies, same IP for both requests
            session = requests.Session()
            session.proxies.update(proxies)
            session.headers.update(headers)

            # Step 1: Fetch page
            page_url = f'https://www.youtube.com/watch?v={video_id}'
            resp = session.get(page_url, timeout=20)
            if not resp.ok:
                logger.warning(f"Page {resp.status_code} via {proxy_url.split('@')[-1]}")
                continue

            html = resp.text
            match = re.search(r'"captionTracks":\s*(\[.*?\])', html)
            if not match:
                logger.warning(f"No captions for {video_id}")
                return None  # Video has no captions at all

            caption_tracks = json.loads(match.group(1))
            logger.info(f"Found {len(caption_tracks)} caption tracks via {proxy_url.split('@')[-1]}")

            # Pick English track
            caption_url = None
            for track in caption_tracks:
                lang = track.get('languageCode', '')
                if lang.startswith('en'):
                    caption_url = track.get('baseUrl')
                    logger.info(f"Using EN: {lang}")
                    break
            if not caption_url and caption_tracks:
                caption_url = caption_tracks[0].get('baseUrl')
                logger.info(f"Using: {caption_tracks[0].get('languageCode')}")

            if not caption_url:
                return None

            # Step 2: Fetch caption WITH SAME SESSION (same cookies + proxy)
            cap_resp = session.get(caption_url + '&fmt=json3', timeout=20)
            logger.info(f"Caption status: {cap_resp.status_code}")

            if cap_resp.status_code == 429:
                logger.warning(f"Caption 429, trying next proxy")
                continue

            if not cap_resp.ok:
                logger.warning(f"Caption failed: {cap_resp.status_code}")
                continue

            data = cap_resp.json()
            events = data.get('events', [])
            texts = []
            for event in events:
                for seg in event.get('segs', []):
                    t = seg.get('utf8', '').strip()
                    if t and t != '\n':
                        texts.append(t)

            text = ' '.join(texts).strip()
            if text:
                logger.info(f"Transcript success! chars={len(text)}")
                return text

        except Exception as e:
            logger.warning(f"Proxy {proxy_url.split('@')[-1]} error: {e}")
            continue

    logger.error("All proxies failed for transcript")
    return None


def get_cookies_path():
    secrets_path = '/etc/secrets/cookies.txt'
    if not os.path.exists(secrets_path):
        return None
    try:
        tmp = '/tmp/yt_cookies.txt'
        shutil.copy2(secrets_path, tmp)
        return tmp
    except Exception:
        return None


def transcribe_with_groq(url):
    try:
        import yt_dlp
        import requests
        from groq import Groq

        groq_key = os.environ.get('GROQ_API_KEY')
        if not groq_key:
            return None, None

        client = Groq(api_key=groq_key)
        cookies_path = get_cookies_path()
        proxies_list = get_proxies_list()
        proxy_url = proxies_list[0] if proxies_list else None

        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extractor_args': {
                'youtube': {'player_client': ['ios', 'android', 'web']}
            },
        }
        if cookies_path:
            ydl_opts['cookiefile'] = cookies_path
        if proxy_url:
            ydl_opts['proxy'] = proxy_url

        audio_url = None
        title = 'Video'

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Video')
                formats = info.get('formats', [])
                for f in reversed(formats):
                    if f.get('acodec') not in (None, 'none') and f.get('url'):
                        audio_url = f['url']
                        break
                if not audio_url:
                    audio_url = info.get('url')
        except Exception as e:
            logger.warning(f"yt-dlp failed: {e}")

        if not audio_url:
            return None, title

        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.youtube.com/'}
        proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

        audio_resp = requests.get(audio_url, headers=headers, proxies=proxies, timeout=120, stream=True)
        if not audio_resp.ok:
            logger.error(f"Audio download failed: {audio_resp.status_code}")
            return None, title

        with tempfile.NamedTemporaryFile(suffix='.m4a', delete=False) as tmp_f:
            tmp_path = tmp_f.name
            for chunk in audio_resp.iter_content(chunk_size=32768):
                tmp_f.write(chunk)

        size = os.path.getsize(tmp_path)
        logger.info(f"Audio {size} bytes → Groq")

        with open(tmp_path, 'rb') as f:
            transcription = client.audio.transcriptions.create(
                file=('audio.m4a', f.read()),
                model='whisper-large-v3',
                response_format='text'
            )
        os.unlink(tmp_path)
        return str(transcription), title

    except Exception as e:
        logger.error(f"Groq failed: {e}")
        return None, None


@api_bp.route('/health', methods=['GET'])
def health():
    proxies = get_proxies_list()
    return jsonify({
        'status': 'ok',
        'service': 'WhisperTube',
        'proxy_count': len(proxies),
        'cookies': os.path.exists('/etc/secrets/cookies.txt'),
        'groq': bool(os.environ.get('GROQ_API_KEY'))
    })


@api_bp.route('/transcribe', methods=['POST'])
def transcribe():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON body'}), 400
        url = data.get('url', '').strip()
        if not url:
            return jsonify({'error': 'url is required'}), 400

        logger.info(f"=== Transcribing: {url} ===")
        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({'error': 'Invalid YouTube URL'}), 400

        transcript = get_youtube_transcript(video_id)
        if transcript and len(transcript) > 20:
            return jsonify({'transcript': transcript, 'title': video_id, 'method': 'transcript_api'})

        transcript, title = transcribe_with_groq(url)
        if transcript:
            return jsonify({'transcript': transcript, 'title': title or video_id, 'method': 'groq'})

        return jsonify({'error': 'Could not transcribe this video'}), 422

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500