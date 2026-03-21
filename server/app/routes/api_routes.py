"""API routes for mobile app integration"""
from flask import Blueprint, request, jsonify, session
from app.services.context_loader import load_context
from app.services.ai_service import answer_question_with_context, translate
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__)


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for mobile app"""
    return jsonify({
        'status': 'healthy',
        'version': '2.0',
        'timestamp': datetime.now().isoformat(),
        'service': 'VirtualClone API'
    })


@api_bp.route('/chat', methods=['POST'])
def chat():
    """
    Chat endpoint for mobile app

    Request JSON:
    {
        "message": "user message",
        "language": "eng_Latn" (optional)
    }

    Response JSON:
    {
        "success": true,
        "response": "bot response",
        "message": "original message",
        "timestamp": "ISO timestamp"
    }
    """
    try:
        data = request.get_json()

        if not data or 'message' not in data:
            return jsonify({
                'success': False,
                'error': 'Message is required'
            }), 400

        user_message = data['message']
        language = data.get('language', 'eng_Latn')

        # Get conversation history from session
        conversation_history = session.get('conversation_history', [])
        recent_history = conversation_history[-5:] if conversation_history else []

        # Get context and process question
        context = load_context()

        # Handle translation if needed
        if language != 'eng_Latn':
            try:
                # Translate question to English
                eng_question = translate(user_message, src_lang=language, tgt_lang='eng_Latn')
                # Get answer in English
                eng_response = answer_question_with_context(eng_question, context, recent_history)
                # Translate response back to target language
                response = translate(eng_response, src_lang='eng_Latn', tgt_lang=language)
            except Exception as e:
                logger.error(f"Translation error: {e}")
                # Fallback to English
                response = answer_question_with_context(user_message, context, recent_history)
        else:
            response = answer_question_with_context(user_message, context, recent_history)

        # Update conversation history
        conversation_history.append((user_message, response))
        session['conversation_history'] = conversation_history[-10:]  # Keep last 10

        return jsonify({
            'success': True,
            'response': response,
            'message': user_message,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An error occurred processing your message',
            'details': str(e) if logger.level == logging.DEBUG else None
        }), 500


@api_bp.route('/reset-session', methods=['POST'])
def reset_session():
    """Reset conversation session"""
    try:
        session.clear()
        logger.info("Session cleared successfully")
        return jsonify({
            'success': True,
            'message': 'Session cleared successfully'
        })
    except Exception as e:
        logger.error(f"Session reset error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/conversation-history', methods=['GET'])
def get_conversation_history():
    """Get current conversation history"""
    try:
        conversation_history = session.get('conversation_history', [])
        return jsonify({
            'success': True,
            'history': [
                {
                    'question': q,
                    'answer': a,
                    'index': i
                }
                for i, (q, a) in enumerate(conversation_history)
            ],
            'count': len(conversation_history)
        })
    except Exception as e:
        logger.error(f"Get history error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/languages', methods=['GET'])
def get_languages():
    """Get available languages"""
    try:
        from app.constants.languages import languages
        return jsonify({
            'success': True,
            'languages': languages
        })
    except Exception as e:
        logger.error(f"Get languages error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Error handlers for API blueprint
@api_bp.errorhandler(404)
def api_not_found(e):
    """Handle 404 errors"""
    return jsonify({
        'success': False,
        'error': 'Endpoint not found'
    }), 404


@api_bp.errorhandler(500)
def api_internal_error(e):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {e}")
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500
