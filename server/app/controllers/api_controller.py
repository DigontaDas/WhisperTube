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
    """Try youtube-transcript-api v0.6+ first — fast and free."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None
        try:
            transcript = transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
        except Exception:
            pass
        if not transcript:
            try:
                transcript = transcript_list.find_generated_transcript(['en', 'en-US'])
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
            elif hasattr(fetched, '__iter__'):
                text = ' '.join(
                    item.get('text', '') if isinstance(item, dict) else str(item)
                    for item in fetched
                )
            else:
                text = str(fetched)
            if text.strip():
                logger.info(f"Transcript API success for {video_id}")
                return text.strip()
        return None
    except Exception as e:
        logger.warning(f"Transcript API failed for {video_id}: {e}")
        return None


def transcribe_with_groq(url):
    """Download audio with yt-dlp and transcribe with Groq Whisper."""
    try:
        import yt_dlp
        from groq import Groq

        groq_key = os.environ.get('GROQ_API_KEY')
        if not groq_key:
            logger.error("GROQ_API_KEY not set")
            return None, None

        client = Groq(api_key=groq_key)

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
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Video')

            audio_file = None
            for f in os.listdir(tmpdir):
                if f.endswith(('.mp3', '.m4a', '.webm', '.opus')):
                    audio_file = os.path.join(tmpdir, f)
                    break

            if not audio_file:
                logger.error("No audio file found after yt-dlp")
                return None, title

            logger.info(f"Sending to Groq: {audio_file}")
            with open(audio_file, 'rb') as f:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_file), f.read()),
                    model='whisper-large-v3',
                    response_format='text'
                )
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

        # Try transcript API first (fast, no download needed)
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

        return jsonify({'error': 'Could not transcribe this video'}), 422

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'error': str(e)}), 500