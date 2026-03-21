#import whisper
import os
import subprocess
import json

# Optional import: make faster_whisper lazy/optional to avoid heavy dependency during tests
try:
    from faster_whisper import WhisperModel  # type: ignore
    _FW_AVAILABLE = True
except Exception:  # pragma: no cover - environments without faster_whisper
    WhisperModel = None  # type: ignore
    _FW_AVAILABLE = False

# Lazy model initialization
_model = None

def _get_model():
    global _model
    if _model is None:
        if WhisperModel is None:
            raise RuntimeError("faster_whisper is not installed; transcription is unavailable.")
        _model = WhisperModel("tiny")
    return _model

def extract_audio(video_path, audio_path):
    try:
        command = [
            "ffmpeg", "-i", video_path,
            "-vn",  # no video
            "-acodec", "pcm_s16le",  # WAV format
            "-ar", "16000",          # 16kHz sample rate
            "-ac", "1",              # mono audio
            audio_path
        ]

        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except Exception as e:
        print(f"Error extracting audio: {e}")

def transcribe_audio(audio_path):
    try:
        if not os.path.exists(audio_path) or not is_valid_audio(audio_path):
            raise Exception(f"Invalid audio file: {audio_path}")
        
        model = _get_model()
        segments, info = model.transcribe(audio_path)
        text = " ".join([segment.text for segment in segments if segment.text.strip()])
        #result = model.transcribe(audio_path)
        #text = result['text']

        BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        DATA_DIR = os.path.join(BASE_DIR, "data")

        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "train.jsonl"), "a", encoding="utf-8") as f:
            json.dump({"text": text.strip()}, f, ensure_ascii=False)
            f.write("\n")

        return text
    except Exception as e:
        print(f"Error transcribing audio: {e}")
        return None
    

def is_valid_audio(audio_path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        duration = float(result.stdout.strip())
        return duration > 0.5  # skip files shorter than 0.5s
    except Exception:
        return False

