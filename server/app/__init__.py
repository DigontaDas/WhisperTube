from flask import Flask
from flask_cors import CORS
import logging

def create_app():
    app = Flask(__name__)
    
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    })

    from app.controllers.api_controller import api_bp
    app.register_blueprint(api_bp)

    logger.info("WhisperTube server started")
    return app