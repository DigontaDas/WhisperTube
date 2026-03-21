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
    """
    Uses youtube-transcript-api.
    Installed version has: fetch, list methods.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # Method: fetch(video_id) — the correct call for this version
        try:
            fetched = YouTubeTranscriptApi.fetch(video_id)
            logger.info(f"fetch() returned type: {type(fetched)}")

            # Handle FetchedTranscript object (has .snippets)
            if hasattr(fetched, 'snippets'):
                text = ' '.join(s.text for s in fetched.snippets)
                logger.info(f"fetch via snippets, chars={len(text)}")
                if text.strip():
                    return text.strip()

            # Handle list of dicts
            if hasattr(fetched, '__iter__'):
                items = list(fetched)
                logger.info(f"fetch returned {len(items)} items, first={items[0] if items else 'empty'}")
                text = ' '.join(
                    item.get('text', '') if isinstance(item, dict) else
                    (item.text if hasattr(item, 'text') else str(item))
                    for item in items
                )
                if text.strip():
                    logger.info(f"fetch via iter, chars={len(text)}")
                    return text.strip()

        except Exception as e:
            logger.warning(f"fetch(video_id) failed: {e}")

        # Method: list(video_id) — list available transcripts
        try:
            transcript_list = YouTubeTranscriptApi.list(video_id)
            logger.info(f"list() returned type: {type(transcript_list)}")

            # Try to get first available transcript
            transcript = None
            # Try English first
            for lang in ['en', 'en-US', 'en-GB']:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    break
                except Exception:
                    pass

            # Any transcript
            if not transcript:
                try:
                    for t in transcript_list:
                        transcript = t
                        logger.info(f"Using transcript: {t.language_code}")
                        break
                except Exception:
                    pass

            if transcript:
                fetched = transcript.fetch()
                if hasattr(fetched, 'snippets'):
                    text = ' '.join(s.text for s in fetched.snippets)
                else:
                    text = ' '.join(
                        item.get('text', '') if isinstance(item, dict) else
                        (item.text if hasattr(item, 'text') else str(item))
                        for item in fetched
                    )
                if text.strip():
                    logger.info(f"list().fetch() success, chars={len(text)}")
                    return text.strip()

        except Exception as e:
            logger.warning(f"list(video_id) failed: {e}")

        logger.warning(f"All transcript methods failed for {video_id}")
        return None

    except Exception as e:
        logger.error(f"Transcript API import/error: {e}")
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


def transcribe_with_groq(url, video_id):
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
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '96',
                }],
                'quiet': True,
                'no_warnings': True,
                # Use Android client — less likely to hit bot detection
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                    }
                },
            }

            if cookies_path:
                ydl_opts['cookiefile'] = cookies_path
                logger.info(f"Using cookies: {cookies_path}")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Video')

            audio_file = None
            for f in os.listdir(tmpdir):
                if f.endswith(('.mp3', '.m4a', '.webm', '.opus', '.ogg', '.wav')):
                    audio_file = os.path.join(tmpdir, f)
                    break

            if not audio_file:
                logger.error("No audio file found")
                return None, title

            logger.info(f"Sending to Groq: {os.path.basename(audio_file)}")
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
        from youtube_transcript_api import YouTubeTranscriptApi
        methods = [m for m in dir(YouTubeTranscriptApi) if not m.startswith('_')]
        yta_info = str(methods)
    except Exception as e:
        yta_info = f"error: {e}"
    return jsonify({
        'status': 'ok',
        'service': 'WhisperTube',
        'yta_methods': yta_info,
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

        # Method 1: transcript API
        transcript = get_youtube_transcript(video_id)
        if transcript and len(transcript) > 20:
            return jsonify({
                'transcript': transcript,
                'title': video_id,
                'method': 'transcript_api'
            })

        # Method 2: yt-dlp + Groq
        transcript, title = transcribe_with_groq(url, video_id)
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