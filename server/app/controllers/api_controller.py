from flask import Blueprint, request, jsonify
import logging
import os
import re
import tempfile
import shutil

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


def get_proxy():
    """Single proxy URL from WEBSHARE_PROXY env var."""
    return os.environ.get('WEBSHARE_PROXY', '').strip()


def get_youtube_transcript(video_id):
    import requests
    import json

    proxy_url = get_proxy()
    if not proxy_url:
        logger.warning("No proxy set")
        return None

    proxies = {'http': proxy_url, 'https': proxy_url}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    try:
        # Use ONE session for both page + caption — same cookies, same IP
        session = requests.Session()
        session.proxies.update(proxies)
        session.headers.update(headers)

        page_resp = session.get(
            f'https://www.youtube.com/watch?v={video_id}',
            timeout=20
        )
        logger.info(f"Page status: {page_resp.status_code}")
        if not page_resp.ok:
            return None

        match = re.search(r'"captionTracks":\s*(\[.*?\])', page_resp.text)
        if not match:
            logger.warning(f"No captions for {video_id}")
            return None

        tracks = json.loads(match.group(1))
        logger.info(f"Found {len(tracks)} caption tracks")

        caption_url = None
        for t in tracks:
            if t.get('languageCode', '').startswith('en'):
                caption_url = t.get('baseUrl')
                break
        if not caption_url:
            caption_url = tracks[0].get('baseUrl') if tracks else None
        if not caption_url:
            return None

        cap_resp = session.get(caption_url + '&fmt=json3', timeout=20)
        logger.info(f"Caption status: {cap_resp.status_code}")
        if not cap_resp.ok:
            return None

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
        return None

    except Exception as e:
        logger.error(f"Transcript error: {e}")
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
        proxy_url = get_proxy()
        proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'skip_download': True,
            'extractor_args': {'youtube': {'player_client': ['ios', 'android']}},
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
                for f in reversed(info.get('formats', [])):
                    if f.get('acodec') not in (None, 'none') and f.get('url'):
                        audio_url = f['url']
                        break
                if not audio_url:
                    audio_url = info.get('url')
        except Exception as e:
            logger.warning(f"yt-dlp failed: {e}")

        if not audio_url:
            return None, title

        audio_resp = requests.get(
            audio_url,
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.youtube.com/'},
            proxies=proxies, timeout=120, stream=True
        )
        if not audio_resp.ok:
            return None, title

        with tempfile.NamedTemporaryFile(suffix='.m4a', delete=False) as f:
            tmp_path = f.name
            for chunk in audio_resp.iter_content(32768):
                f.write(chunk)

        logger.info(f"Audio {os.path.getsize(tmp_path)} bytes → Groq")
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
    proxy = get_proxy()
    return jsonify({
        'status': 'ok',
        'service': 'WhisperTube',
        'proxy': proxy.split('@')[-1] if proxy else 'not set',
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