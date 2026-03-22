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
    Fetch transcript using requests session with proxy.
    youtube-transcript-api 1.x uses requests internally.
    We patch the session before calling.
    """
    proxy_url = get_proxy()

    try:
        import requests as req_module
        from youtube_transcript_api import YouTubeTranscriptApi

        if proxy_url:
            # Patch requests at module level before API call
            import youtube_transcript_api._transcripts as transcripts_module
            original_session_class = None

            session = req_module.Session()
            session.proxies = {'http': proxy_url, 'https': proxy_url}
            session.verify = True

            # Replace the requests.Session used internally
            original_Session = req_module.Session

            class ProxiedSession(req_module.Session):
                def __init__(self):
                    super().__init__()
                    self.proxies = {'http': proxy_url, 'https': proxy_url}

            req_module.Session = ProxiedSession

        ytt = YouTubeTranscriptApi()
        fetched = ytt.fetch(video_id)

        if proxy_url:
            req_module.Session = original_Session  # restore

        text = ' '.join(s.text for s in fetched.snippets)
        if text.strip():
            logger.info(f"Transcript success for {video_id}, chars={len(text)}")
            return text.strip()
        return None

    except Exception as e:
        if proxy_url:
            try:
                req_module.Session = original_Session
            except Exception:
                pass
        logger.warning(f"Transcript failed: {str(e)[:150]}")
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

        groq_key = os.environ.get('GROQ_API_KEY')
        if not groq_key:
            return None, None

        client = Groq(api_key=groq_key)
        cookies_path = get_cookies_path()
        proxy_url = get_proxy()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Try downloading without format restriction first
            ydl_opts = {
                'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '96',
                }],
                'quiet': True,
                'no_warnings': True,
            }
            if cookies_path:
                ydl_opts['cookiefile'] = cookies_path
            if proxy_url:
                ydl_opts['proxy'] = proxy_url

            # Try formats in order
            formats_to_try = [
                'bestaudio[ext=m4a]',
                'bestaudio[ext=webm]',
                'bestaudio',
                'best[height<=360]',
                'best',
                None,  # no format = yt-dlp decides
            ]

            info = None
            for fmt in formats_to_try:
                try:
                    opts = dict(ydl_opts)
                    if fmt:
                        opts['format'] = fmt
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                    logger.info(f"yt-dlp success with format: {fmt}")
                    break
                except Exception as e:
                    logger.warning(f"yt-dlp format {fmt} failed: {str(e)[:80]}")
                    continue

            if not info:
                logger.error("All yt-dlp formats failed")
                return None, None

            title = info.get('title', 'Video')
            audio_file = None
            for f in os.listdir(tmpdir):
                if f.endswith(('.mp3', '.m4a', '.webm', '.opus', '.ogg', '.wav', '.mp4')):
                    audio_file = os.path.join(tmpdir, f)
                    break

            if not audio_file:
                logger.error("No audio file in tmpdir")
                return None, title

            file_size = os.path.getsize(audio_file)
            logger.info(f"Sending to Groq: {os.path.basename(audio_file)} ({file_size} bytes)")

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

        return jsonify({'error': 'Could not transcribe this video'}), 422

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500