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


def get_youtube_transcript(video_id):
    """Try every possible transcript API method with full logging."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        import inspect
        
        # Log what methods are available
        methods = [m for m in dir(YouTubeTranscriptApi) if not m.startswith('_')]
        logger.info(f"YouTubeTranscriptApi methods: {methods}")

        # Method 1: get_transcript (most common)
        if hasattr(YouTubeTranscriptApi, 'get_transcript'):
            try:
                data = YouTubeTranscriptApi.get_transcript(video_id)
                text = ' '.join(item.get('text', '') for item in data)
                if text.strip():
                    logger.info(f"get_transcript success, chars={len(text)}")
                    return text.strip()
            except Exception as e:
                logger.warning(f"get_transcript failed: {e}")

        # Method 2: list_transcripts
        if hasattr(YouTubeTranscriptApi, 'list_transcripts'):
            try:
                tlist = YouTubeTranscriptApi.list_transcripts(video_id)
                for t in tlist:
                    try:
                        fetched = t.fetch()
                        if hasattr(fetched, 'snippets'):
                            text = ' '.join(s.text for s in fetched.snippets)
                        else:
                            text = ' '.join(
                                i.get('text', '') if isinstance(i, dict) else str(i)
                                for i in fetched
                            )
                        if text.strip():
                            logger.info(f"list_transcripts success, lang={t.language_code}")
                            return text.strip()
                    except Exception as e:
                        logger.warning(f"fetch transcript {t.language_code} failed: {e}")
            except Exception as e:
                logger.warning(f"list_transcripts failed: {e}")

        logger.warning(f"All transcript methods failed for {video_id}")
        return None

    except ImportError as e:
        logger.error(f"youtube_transcript_api not installed: {e}")
        return None
    except Exception as e:
        logger.error(f"Transcript error: {e}")
        return None


def get_cookies_path():
    secrets_path = '/etc/secrets/cookies.txt'
    if not os.path.exists(secrets_path):
        logger.info("No cookies file found")
        return None
    try:
        tmp_cookies = '/tmp/yt_cookies.txt'
        shutil.copy2(secrets_path, tmp_cookies)
        logger.info(f"Cookies copied to {tmp_cookies}")
        return tmp_cookies
    except Exception as e:
        logger.warning(f"Could not copy cookies: {e}")
        return None


def transcribe_with_groq(url):
    """Download audio with yt-dlp and transcribe with Groq."""
    try:
        import yt_dlp
        from groq import Groq

        groq_key = os.environ.get('GROQ_API_KEY')
        if not groq_key:
            logger.error("GROQ_API_KEY not set")
            return None, None

        client = Groq(api_key=groq_key)
        cookies_path = get_cookies_path()

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                'format': 'worstaudio/worst/best',  # grab anything available
                'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '96',
                }],
                'quiet': False,  # show errors
                'no_warnings': False,
                'verbose': False,
            }

            if cookies_path:
                ydl_opts['cookiefile'] = cookies_path

            logger.info(f"Starting yt-dlp download for {url}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Video')
                logger.info(f"Downloaded: {title}")

            audio_file = None
            for f in os.listdir(tmpdir):
                full = os.path.join(tmpdir, f)
                logger.info(f"Found file: {f} size={os.path.getsize(full)}")
                if f.endswith(('.mp3', '.m4a', '.webm', '.opus', '.ogg', '.wav')):
                    audio_file = full

            if not audio_file:
                logger.error("No audio file found in tmpdir")
                return None, title

            file_size = os.path.getsize(audio_file)
            logger.info(f"Sending to Groq: {os.path.basename(audio_file)} ({file_size} bytes)")

            with open(audio_file, 'rb') as f:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_file), f.read()),
                    model='whisper-large-v3',
                    response_format='text'
                )
            logger.info(f"Groq done for: {title}")
            return str(transcription), title

    except Exception as e:
        logger.error(f"Groq transcription failed: {e}")
        return None, None


@api_bp.route('/health', methods=['GET'])
def health():
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        methods = [m for m in dir(YouTubeTranscriptApi) if not m.startswith('_')]
        yta_info = f"available, methods: {methods}"
    except Exception as e:
        yta_info = f"error: {e}"
    
    return jsonify({
        'status': 'ok',
        'version': '1.0',
        'service': 'WhisperTube',
        'youtube_transcript_api': yta_info,
        'cookies_exist': os.path.exists('/etc/secrets/cookies.txt'),
        'groq_key_set': bool(os.environ.get('GROQ_API_KEY'))
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

        # Method 1: transcript API
        transcript = get_youtube_transcript(video_id)
        if transcript and len(transcript) > 20:
            return jsonify({
                'transcript': transcript,
                'title': video_id,
                'method': 'transcript_api'
            })

        # Method 2: yt-dlp + Groq
        transcript, title = transcribe_with_groq(url)
        if transcript:
            return jsonify({
                'transcript': transcript,
                'title': title or video_id,
                'method': 'groq'
            })

        return jsonify({'error': 'Could not transcribe this video'}), 422

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500