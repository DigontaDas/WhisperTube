from flask import Blueprint, request, render_template, session, jsonify, current_app
from app.services.context_loader import load_context, reload_context
from app.services.ai_service import translate, answer_question, answer_question_with_context
from app.constants.languages import languages
import logging

logger = logging.getLogger(__name__)
main_bp = Blueprint("main", __name__)

# Load initial context at startup
_base_context = load_context(include_transcripts=True)


def get_active_context():
    """
    Get the current active context, optionally reloading transcripts.
    For now, we cache the context but this can be extended to reload dynamically.
    """
    return _base_context


@main_bp.route("/hello")
def hello():
    return "Hello from main route!"


@main_bp.route("/", methods=["GET", "POST"])
def index():
    """Main chat interface route"""
    logger.info("Main route accessed")
    selected_language = session.get("selected_language", "eng_Latn")

    conversation_history = session.get("conversation_history", [])
    messages = conversation_history

    if request.method == "POST":
        if "language" in request.form:
            selected_language = request.form["language"]
            session["selected_language"] = selected_language
            logger.info(f"Language changed to: {selected_language}")
            return jsonify({"selected_language": languages.get(selected_language, "Unknown")})

        elif "user_input" in request.form:
            user_input = request.form["user_input"]
            logger.info(f"Processing question: {user_input[:50]}...")

            recent_history = conversation_history[-5:] if conversation_history else []

            try:
                # Get fresh context (includes transcripts if available)
                context = get_active_context()
                
                if selected_language != "eng_Latn":
                    logger.debug(f"Translating from {selected_language} to English")
                    eng_question = translate(user_input, src_lang=selected_language, tgt_lang="eng_Latn")

                    eng_answer = answer_question_with_context(eng_question, context, recent_history)

                    logger.debug(f"Translating response back to {selected_language}")
                    translated_answer = translate(eng_answer, src_lang="eng_Latn", tgt_lang=selected_language)
                    response = translated_answer
                else:
                    response = answer_question_with_context(user_input, context, recent_history)

                conversation_history.append((user_input, response))
                session["conversation_history"] = conversation_history[-10:]

                logger.info(f"Response generated successfully (length: {len(response)})")
                return jsonify({"user_input": user_input, "answer": response})

            except Exception as e:
                logger.error(f"Error processing question: {e}", exc_info=True)
                error_response = "I apologize, but I'm having trouble processing your question right now. Please try again."
                return jsonify({"user_input": user_input, "answer": error_response}), 500

    return render_template("index.html", messages=messages,
                           selected_language=selected_language,
                           languages=languages)


@main_bp.route("/refresh-context", methods=["POST"])
def refresh_context():
    """
    Endpoint to manually refresh the context (useful after uploading new content).
    """
    global _base_context
    try:
        _base_context = reload_context(include_transcripts=True)
        logger.info("Context refreshed successfully")
        return jsonify({"status": "success", "message": "Context refreshed", "context_length": len(_base_context)})
    except Exception as e:
        logger.error(f"Error refreshing context: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.route("/reset")
def reset():
    session.clear()
    return "Session and conversation history cleared!"
