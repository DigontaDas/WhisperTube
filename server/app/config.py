import os
from datetime import timedelta

class Config:
    """Application configuration"""
    # Base directories
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    # Flask configuration
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'dev-key-change-in-production')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    # Upload configuration
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))
    DOWNLOADS_FOLDER = os.environ.get('DOWNLOADS_FOLDER', os.path.join(BASE_DIR, 'downloads'))
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 30 * 1024 * 1024))

    # Parse allowed extensions from env
    allowed_exts_str = os.environ.get('ALLOWED_EXTENSIONS', 'mp4,mov,avi,mkv,mp3,wav,pdf')
    ALLOWED_EXTENSIONS = set(allowed_exts_str.split(','))

    MAX_VIDEOS = int(os.environ.get('MAX_VIDEOS', 5))

    # Session configuration
    SESSION_TYPE = os.environ.get('SESSION_TYPE', 'filesystem')
    SESSION_PERMANENT = os.environ.get('SESSION_PERMANENT', 'False').lower() == 'true'
    SESSION_USE_SIGNER = os.environ.get('SESSION_USE_SIGNER', 'True').lower() == 'true'
    PERMANENT_SESSION_LIFETIME = timedelta(
        seconds=int(os.environ.get('PERMANENT_SESSION_LIFETIME', 3600))
    )

    # AI Model configuration
    AI_MODEL_TRANSLATION = os.environ.get('AI_MODEL_TRANSLATION', 'facebook/nllb-200-distilled-600M')
    AI_MODEL_QA = os.environ.get('AI_MODEL_QA', 'deepset/roberta-base-squad2')
    WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'tiny')

    # AI behavior tuning (env-overridable)
    AI_QA_TOP_K_PRIMARY = int(os.environ.get('AI_QA_TOP_K_PRIMARY', 3))
    AI_QA_TOP_K_DIVERSE = int(os.environ.get('AI_QA_TOP_K_DIVERSE', 5))
    AI_MAX_ANSWER_LEN = int(os.environ.get('AI_MAX_ANSWER_LEN', 150))
    CONVERSATION_RECENT_EXCHANGES = int(os.environ.get('CONVERSATION_RECENT_EXCHANGES', 3))
    REPETITION_HISTORY_WINDOW = int(os.environ.get('REPETITION_HISTORY_WINDOW', 5))
    REPETITION_SIMILARITY_THRESHOLD = float(os.environ.get('REPETITION_SIMILARITY_THRESHOLD', 0.7))

    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = os.environ.get('LOG_FILE', os.path.join(BASE_DIR, 'app.log'))

    @staticmethod
    def init_app(app):
        """Initialize application with config"""
        # Create necessary directories
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(Config.DOWNLOADS_FOLDER, exist_ok=True)