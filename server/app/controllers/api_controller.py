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
    return os.environ.get('WEBSHARE_PROXY', None)


def get_youtube_transcript(video_id):
    """
    Fetch transcript via direct HTTP request using proxy.
    Bypasses the youtube-transcript-api proxy issue entirely.
    """
    proxy_url = get_proxy()
    proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

    try:
        import requests

        # Step 1: Get the video page to extract transcript URL
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        url = f'https://www.youtube.com/watch?v={video_id}'
        resp = requests.get(url, headers=headers, proxies=proxies, timeout=15)

        if not resp.ok:
            logger.warning(f"YouTube page fetch failed: {resp.status_code}")
            return None

        html = resp.text

        # Extract captions URL from page HTML
        import json
        # Find captionTracks in the page
        pattern = r'"captionTracks":\s*(\[.*?\])'
        match = re.search(pattern, html)
        if not match:
            logger.warning(f"No captionTracks found for {video_id}")
            return None

        caption_tracks = json.loads(match.group(1))
        logger.info(f"Found {len(caption_tracks)} caption tracks")

        # Find English track
        caption_url = None
        for track in caption_tracks:
            lang = track.get('languageCode', '')
            if lang.startswith('en'):
                caption_url = track.get('baseUrl')
                logger.info(f"Using caption track: {lang}")
                break

        # Fallback: use first available
        if not caption_url and caption_tracks:
            caption_url = caption_tracks[0].get('baseUrl')
            logger.info(f"Using first available caption: {caption_tracks[0].get('languageCode')}")

        if not caption_url:
            logger.warning(f"No caption URL found for {video_id}")
            return None

        # Step 2: Fetch the actual transcript
        caption_resp = requests.get(
            caption_url + '&fmt=json3',
            headers=headers,
            proxies=proxies,
            timeout=15
        )

        if not caption_resp.ok:
            logger.warning(f"Caption fetch failed: {caption_resp.status_code}")
            return None

        data = caption_resp.json()
        events = data.get('events', [])
        texts = []
        for event in events:
            for seg in event.get('segs', []):
                t = seg.get('utf8', '').strip()
                if t and t != '\n':
                    texts.append(t)

        text = ' '.join(texts).strip()
        if text:
            logger.info(f"Direct transcript success for {video_id}, chars={len(text)}")
            return text

        return None

    except Exception as e:
        logger.warning(f"Direct transcript failed: {e}")
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
        from groq import Groq
        import requests

        groq_key = os.environ.get('GROQ_API_KEY')
        if not groq_key:
            return None, None

        client = Groq(api_key=groq_key)
        cookies_path = get_cookies_path()
        proxy_url = get_proxy()

        # First get the audio URL using yt-dlp (skip_download=True)
        # Then download it ourselves with proxy via requests
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extractor_args': {
                'youtube': {'player_client': ['ios', 'android']}
            },
        }
        if cookies_path:
            ydl_opts['cookiefile'] = cookies_path
        if proxy_url:
            ydl_opts['proxy'] = proxy_url

        title = 'Video'
        audio_url = None

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Video')
                # Get direct audio URL
                formats = info.get('formats', [])
                for f in reversed(formats):
                    if f.get('acodec') != 'none' and f.get('url'):
                        audio_url = f['url']
                        break
                if not audio_url and info.get('url'):
                    audio_url = info['url']
        except Exception as e:
            logger.warning(f"yt-dlp info extraction failed: {e}")

        if not audio_url:
            logger.error("Could not get audio URL")
            return None, title

        logger.info(f"Got audio URL, downloading via requests...")

        # Download audio via requests with proxy
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.youtube.com/',
        }
        proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

        audio_resp = requests.get(
            audio_url,
            headers=headers,
            proxies=proxies,
            timeout=120,
            stream=True
        )

        if not audio_resp.ok:
            logger.error(f"Audio download failed: {audio_resp.status_code}")
            return None, title

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix='.m4a', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            for chunk in audio_resp.iter_content(chunk_size=8192):
                tmp_file.write(chunk)

        file_size = os.path.getsize(tmp_path)
        logger.info(f"Audio downloaded: {file_size} bytes")

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
    return jsonify({
        'status': 'ok',
        'service': 'WhisperTube',
        'proxy_set': bool(get_proxy()),
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

        # Method 1: Direct transcript fetch with proxy
        transcript = get_youtube_transcript(video_id)
        if transcript and len(transcript) > 20:
            return jsonify({'transcript': transcript, 'title': video_id, 'method': 'transcript_api'})

        # Method 2: yt-dlp info + requests download + Groq
        transcript, title = transcribe_with_groq(url)
        if transcript:
            return jsonify({'transcript': transcript, 'title': title or video_id, 'method': 'groq'})

        return jsonify({'error': 'Could not transcribe this video'}), 422

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500