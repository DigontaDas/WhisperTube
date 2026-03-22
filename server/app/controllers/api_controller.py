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
    """Get proxy URL from environment variable."""
    return os.environ.get('WEBSHARE_PROXY', None)


def get_youtube_transcript(video_id):
    """Fetch transcript using proxy to bypass cloud IP ban."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api.proxies import WebshareProxyConfig

        proxy_url = get_proxy()

        if proxy_url:
            logger.info(f"Using proxy for transcript API")
            # New 1.x API with proxy support
            proxy_config = WebshareProxyConfig(
                proxy_username=None,  # parsed from URL
                proxy_password=None,
            )
            # Parse proxy URL: http://user:pass@host:port
            import urllib.parse
            parsed = urllib.parse.urlparse(proxy_url)
            ytt_api = YouTubeTranscriptApi(
                proxies={
                    'http': proxy_url,
                    'https': proxy_url,
                }
            )
        else:
            logger.warning("No proxy configured — transcript may fail on cloud IP")
            ytt_api = YouTubeTranscriptApi()

        # Try fetch
        try:
            fetched = ytt_api.fetch(video_id)
            text = ' '.join(s.text for s in fetched.snippets)
            if text.strip():
                logger.info(f"Transcript success for {video_id}, chars={len(text)}")
                return text.strip()
        except Exception as e:
            logger.warning(f"fetch() failed: {str(e)[:100]}")

        # Try list then fetch
        try:
            for t in ytt_api.list(video_id):
                try:
                    fetched = t.fetch()
                    if hasattr(fetched, 'snippets'):
                        text = ' '.join(s.text for s in fetched.snippets)
                    else:
                        text = ' '.join(
                            item.get('text', '') if isinstance(item, dict)
                            else getattr(item, 'text', str(item))
                            for item in fetched
                        )
                    if text.strip():
                        logger.info(f"Transcript via list, lang={t.language_code}")
                        return text.strip()
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"list() failed: {str(e)[:100]}")

        return None

    except Exception as e:
        logger.error(f"Transcript API error: {e}")
        return None


def get_cookies_path():
    secrets_path = '/etc/secrets/cookies.txt'
    if not os.path.exists(secrets_path):
        return None
    try:
        tmp_cookies = '/tmp/yt_cookies.txt'
        shutil.copy2(secrets_path, tmp_cookies)
        return tmp_cookies
    except Exception as e:
        logger.warning(f"Could not copy cookies: {e}")
        return None


def transcribe_with_groq(url):
    try:
        import yt_dlp
        from groq import Groq

        groq_key = os.environ.get('GROQ_API_KEY')
        if not groq_key:
            logger.error("GROQ_API_KEY not set")
            return None, None

        client = Groq(api_key=groq_key)
        cookies_path = get_cookies_path()
        proxy_url = get_proxy()

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '96',
                }],
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {'player_client': ['android', 'web']}
                },
            }
            if cookies_path:
                ydl_opts['cookiefile'] = cookies_path
            if proxy_url:
                ydl_opts['proxy'] = proxy_url
                logger.info("Using proxy for yt-dlp")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Video')

            audio_file = None
            for f in os.listdir(tmpdir):
                if f.endswith(('.mp3', '.m4a', '.webm', '.opus', '.ogg')):
                    audio_file = os.path.join(tmpdir, f)
                    break

            if not audio_file:
                return None, title

            with open(audio_file, 'rb') as f:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_file), f.read()),
                    model='whisper-large-v3',
                    response_format='text'
                )
            return str(transcription), title

    except Exception as e:
        logger.error(f"Groq failed: {e}")
        return None, None


@api_bp.route('/health', methods=['GET'])
def health():
    try:
        import youtube_transcript_api as yta
        ver = getattr(yta, '__version__', 'unknown')
    except Exception as e:
        ver = str(e)
    return jsonify({
        'status': 'ok',
        'service': 'WhisperTube',
        'yta_version': ver,
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

        transcript = get_youtube_transcript(video_id)
        if transcript and len(transcript) > 20:
            return jsonify({'transcript': transcript, 'title': video_id, 'method': 'transcript_api'})

        transcript, title = transcribe_with_groq(url)
        if transcript:
            return jsonify({'transcript': transcript, 'title': title or video_id, 'method': 'groq'})

        return jsonify({'error': 'Could not transcribe. Make sure WEBSHARE_PROXY is set in Render environment.'}), 422

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500