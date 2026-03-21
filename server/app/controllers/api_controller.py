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
    """Try youtube-transcript-api - compatible with all versions."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # Try get_transcript (works in most versions)
        if hasattr(YouTubeTranscriptApi, 'get_transcript'):
            try:
                data = YouTubeTranscriptApi.get_transcript(
                    video_id, languages=['en', 'en-US', 'en-GB']
                )
                text = ' '.join(item.get('text', '') for item in data)
                if text.strip():
                    logger.info(f"get_transcript success for {video_id}")
                    return text.strip()
            except Exception as e1:
                logger.warning(f"get_transcript en failed: {e1}")
                try:
                    data = YouTubeTranscriptApi.get_transcript(video_id)
                    text = ' '.join(item.get('text', '') for item in data)
                    if text.strip():
                        return text.strip()
                except Exception as e2:
                    logger.warning(f"get_transcript any failed: {e2}")

        # Try list_transcripts (newer versions)
        if hasattr(YouTubeTranscriptApi, 'list_transcripts'):
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript = None
                try:
                    transcript = transcript_list.find_manually_created_transcript(
                        ['en', 'en-US', 'en-GB']
                    )
                except Exception:
                    pass
                if not transcript:
                    try:
                        transcript = transcript_list.find_generated_transcript(
                            ['en', 'en-US']
                        )
                    except Exception:
                        pass
                if not transcript:
                    for t in transcript_list:
                        transcript = t
                        break
                if transcript:
                    fetched = transcript.fetch()
                    if hasattr(fetched, 'snippets'):
                        text = ' '.join(s.text for s in fetched.snippets)
                    else:
                        text = ' '.join(
                            item.get('text', '') if isinstance(item, dict)
                            else str(item) for item in fetched
                        )
                    if text.strip():
                        logger.info(f"list_transcripts success for {video_id}")
                        return text.strip()
            except Exception as e:
                logger.warning(f"list_transcripts failed: {e}")

        return None

    except Exception as e:
        logger.warning(f"Transcript API error for {video_id}: {e}")
        return None


def get_cookies_path():
    """Copy read-only secrets file to writable temp location if needed."""
    secrets_path = '/etc/secrets/cookies.txt'
    if not os.path.exists(secrets_path):
        return None
    try:
        # /etc/secrets is read-only on Render — copy to /tmp
        tmp_cookies = '/tmp/yt_cookies.txt'
        shutil.copy2(secrets_path, tmp_cookies)
        os.chmod(tmp_cookies, 0o644)
        logger.info(f"Cookies copied to {tmp_cookies}")
        return tmp_cookies
    except Exception as e:
        logger.warning(f"Could not copy cookies: {e}")
        # Try using directly
        return secrets_path


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
                # More flexible format selection
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',
                }],
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }

            if cookies_path:
                ydl_opts['cookiefile'] = cookies_path
                logger.info(f"Using cookies: {cookies_path}")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Video')

            audio_file = None
            for f in os.listdir(tmpdir):
                if f.endswith(('.mp3', '.m4a', '.webm', '.opus', '.ogg')):
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
            logger.info(f"Groq done: {title}")
            return str(transcription), title

    except Exception as e:
        logger.error(f"Groq transcription failed: {e}")
        return None, None


@api_bp.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'version': '1.0', 'service': 'WhisperTube'})


@api_bp.route('/transcribe', methods=['POST'])
def transcribe():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON body'}), 400

        url = data.get('url', '').strip()
        if not url:
            return jsonify({'error': 'url is required'}), 400

        logger.info(f"Transcribing: {url}")
        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({'error': 'Invalid YouTube URL'}), 400

        # Method 1: transcript API (fast, no download)
        transcript = get_youtube_transcript(video_id)
        if transcript and len(transcript) > 20:
            return jsonify({
                'transcript': transcript,
                'title': video_id,
                'method': 'transcript_api'
            })

        # Method 2: yt-dlp + Groq
        logger.info(f"Falling back to Groq for {video_id}")
        transcript, title = transcribe_with_groq(url)
        if transcript:
            return jsonify({
                'transcript': transcript,
                'title': title or video_id,
                'method': 'groq'
            })

        return jsonify({
            'error': 'Could not transcribe this video. '
                     'Try a video with auto-generated captions enabled.'
        }), 422

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500