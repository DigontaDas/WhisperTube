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
    # Try multi first, then single
    multi = os.environ.get('WEBSHARE_PROXIES', '').strip()
    if multi:
        return [p.strip() for p in multi.split(',') if p.strip()]
    single = os.environ.get('WEBSHARE_PROXY', '').strip()
    if single:
        return [single]
    return []


def get_youtube_transcript(video_id):
    import requests
    import json

    proxies_list = get_proxies_list()
    logger.info(f"Trying transcript with {len(proxies_list)} proxies")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    # Shuffle so we don't always hammer the same proxy
    random.shuffle(proxies_list)

    for proxy_url in proxies_list:
        proxies = {'http': proxy_url, 'https': proxy_url}
        label = proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url
        try:
            session = requests.Session()
            session.proxies.update(proxies)
            session.headers.update(headers)

            page_resp = session.get(
                f'https://www.youtube.com/watch?v={video_id}',
                timeout=20
            )
            logger.info(f"Page {page_resp.status_code} via {label}")

            if page_resp.status_code == 429:
                logger.warning(f"Page 429 on {label}, trying next proxy")
                continue
            if not page_resp.ok:
                continue

            match = re.search(r'"captionTracks":\s*(\[.*?\])', page_resp.text)
            if not match:
                logger.warning(f"No captions for {video_id}")
                return None  # No captions — don't try other proxies

            tracks = json.loads(match.group(1))
            logger.info(f"Found {len(tracks)} tracks")

            caption_url = None
            for t in tracks:
                if t.get('languageCode', '').startswith('en'):
                    caption_url = t.get('baseUrl')
                    break
            if not caption_url and tracks:
                caption_url = tracks[0].get('baseUrl')
            if not caption_url:
                return None

            cap_resp = session.get(caption_url + '&fmt=json3', timeout=20)
            logger.info(f"Caption {cap_resp.status_code} via {label}")

            if cap_resp.status_code == 429:
                continue
            if not cap_resp.ok:
                continue

            events = cap_resp.json().get('events', [])
            texts = [
                seg.get('utf8', '').strip()
                for event in events
                for seg in event.get('segs', [])
                if seg.get('utf8', '').strip() not in ('', '\n')
            ]
            text = ' '.join(texts).strip()
            if text:
                logger.info(f"Transcript success! chars={len(text)}")
                return text

        except Exception as e:
            logger.warning(f"Proxy {label} error: {e}")
            continue

    logger.error("All proxies failed — consider upgrading to residential proxies")
    return None


def get_cookies_path():
    path = '/etc/secrets/cookies.txt'
    if not os.path.exists(path):
        return None
    try:
        tmp = '/tmp/yt_cookies.txt'
        shutil.copy2(path, tmp)
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

        audio_url = None
        title = 'Video'

        # Try each proxy for yt-dlp info
        for proxy_url in proxies_list:
            try:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'quiet': True,
                    'no_warnings': True,
                    'skip_download': True,
                    'extractor_args': {
                        'youtube': {'player_client': ['web']}  # web supports cookies
                    },
                }
                if cookies_path:
                    ydl_opts['cookiefile'] = cookies_path
                if proxy_url:
                    ydl_opts['proxy'] = proxy_url

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', 'Video')
                    for f in reversed(info.get('formats', [])):
                        if f.get('acodec') not in (None, 'none') and f.get('url'):
                            audio_url = f['url']
                            break
                    if not audio_url:
                        audio_url = info.get('url')

                if audio_url:
                    logger.info(f"Got audio URL via {proxy_url.split('@')[-1]}")
                    break
            except Exception as e:
                logger.warning(f"yt-dlp failed on {proxy_url.split('@')[-1]}: {str(e)[:80]}")
                continue

        if not audio_url:
            return None, title

        # Download audio
        proxy_url = proxies_list[0] if proxies_list else None
        proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.youtube.com/'}

        audio_resp = requests.get(audio_url, headers=headers, proxies=proxies, timeout=120, stream=True)
        if not audio_resp.ok:
            logger.error(f"Audio download {audio_resp.status_code}")
            return None, title

        with tempfile.NamedTemporaryFile(suffix='.m4a', delete=False) as f:
            tmp_path = f.name
            for chunk in audio_resp.iter_content(32768):
                f.write(chunk)

        size = os.path.getsize(tmp_path)
        logger.info(f"Audio {size} bytes → Groq")

        with open(tmp_path, 'rb') as f:
            result = client.audio.transcriptions.create(
                file=('audio.m4a', f.read()),
                model='whisper-large-v3',
                response_format='text'
            )
        os.unlink(tmp_path)
        return str(result), title

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
        'proxies': [p.split('@')[-1] for p in proxies],
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