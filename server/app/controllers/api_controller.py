from flask import Blueprint, request, jsonify
import logging
import os
import re
import tempfile

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
    """Try youtube-transcript-api - works with both old and new API versions."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        transcript_data = None

        # New API (0.7+): list_transcripts
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
                        transcript_data = [
                            {'text': s.text} for s in fetched.snippets
                        ]
                    else:
                        transcript_data = list(fetched)
            except Exception as e:
                logger.warning(f"list_transcripts failed: {e}")

        # Old API (0.6.x): get_transcript
        if not transcript_data and hasattr(YouTubeTranscriptApi, 'get_transcript'):
            try:
                transcript_data = YouTubeTranscriptApi.get_transcript(
                    video_id, languages=['en', 'en-US', 'en-GB']
                )
            except Exception:
                try:
                    transcript_data = YouTubeTranscriptApi.get_transcript(video_id)
                except Exception as e:
                    logger.warning(f"get_transcript failed: {e}")

        # Even older API: fetch
        if not transcript_data:
            try:
                fetched = YouTubeTranscriptApi.fetch(video_id)
                if hasattr(fetched, 'snippets'):
                    transcript_data = [{'text': s.text} for s in fetched.snippets]
                else:
                    transcript_data = list(fetched)
            except Exception as e:
                logger.warning(f"fetch failed: {e}")

        if transcript_data:
            text = ' '.join(
                item.get('text', '') if isinstance(item, dict) else str(item)
                for item in transcript_data
            )
            if text.strip():
                logger.info(f"Transcript success for {video_id}")
                return text.strip()

        return None

    except Exception as e:
        logger.warning(f"Transcript API error for {video_id}: {e}")
        return None


def transcribe_with_groq(url):
    """Download audio with yt-dlp + cookies and transcribe with Groq."""
    try:
        import yt_dlp
        from groq import Groq

        groq_key = os.environ.get('GROQ_API_KEY')
        if not groq_key:
            logger.error("GROQ_API_KEY not set")
            return None, None

        client = Groq(api_key=groq_key)

        # Check if cookies file exists (uploaded to Render)
        cookies_file = os.environ.get('YOUTUBE_COOKIES_FILE', '/etc/secrets/cookies.txt')
        cookies_exist = os.path.exists(cookies_file)
        logger.info(f"Cookies file exists: {cookies_exist} at {cookies_file}")

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',
                }],
                'quiet': True,
                'no_warnings': True,
            }

            # Add cookies if available
            if cookies_exist:
                ydl_opts['cookiefile'] = cookies_file
                logger.info("Using cookies for yt-dlp")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Video')

            audio_file = None
            for f in os.listdir(tmpdir):
                if f.endswith(('.mp3', '.m4a', '.webm', '.opus')):
                    audio_file = os.path.join(tmpdir, f)
                    break

            if not audio_file:
                logger.error("No audio file found")
                return None, title

            with open(audio_file, 'rb') as f:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_file), f.read()),
                    model='whisper-large-v3',
                    response_format='text'
                )
            logger.info(f"Groq transcription done: {title}")
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

        # Try transcript API first
        transcript = get_youtube_transcript(video_id)
        if transcript and len(transcript) > 20:
            return jsonify({
                'transcript': transcript,
                'title': video_id,
                'method': 'transcript_api'
            })

        # Fall back to yt-dlp + Groq
        logger.info(f"Falling back to Groq for {video_id}")
        transcript, title = transcribe_with_groq(url)
        if transcript:
            return jsonify({
                'transcript': transcript,
                'title': title or video_id,
                'method': 'groq'
            })

        return jsonify({
            'error': 'Could not transcribe. Video has no captions and audio download was blocked. '
                     'Try a video with auto-generated captions.'
        }), 422

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500