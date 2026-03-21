from flask import render_template, current_app
from app.services.file_service import save_file, allowed_file
from app.services.transcribe_service import extract_audio, transcribe_audio
import os
import logging

logger = logging.getLogger(__name__)


def handle_upload(request):
    """
    Handle file upload, extract audio, transcribe, and save to train.jsonl.
    Supports video, audio, and PDF files.
    """
    file = request.files.get('file')
    if not file or file.filename == '':
        return "No file selected", 400

    try:
        if not allowed_file(file.filename):
            return "Invalid file type", 400

        filename = save_file(file)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file_ext = filename.rsplit('.', 1)[1].lower()

        transcript = ""

        # Handle PDF files
        if file_ext == 'pdf':
            logger.info(f"Processing PDF file: {filename}")
            transcript = extract_text_from_pdf(file_path)
            if transcript:
                save_pdf_text_to_jsonl(file_path, transcript)
                logger.info(f"PDF text extracted and saved ({len(transcript)} chars)")
            else:
                logger.warning(f"No text extracted from PDF: {filename}")
                transcript = "No text could be extracted from the PDF."

        # Handle video/audio files
        else:
            logger.info(f"Processing media file: {filename}")
            audio_path = file_path.rsplit('.', 1)[0] + ".wav"
            extract_audio(file_path, audio_path)
            transcript = transcribe_audio(audio_path)

        allowed_exts = current_app.config['ALLOWED_EXTENSIONS']
        
        # Auto-refresh context after successful upload
        try:
            from app.services.context_loader import reload_context
            import app.routes.main_routes as main_routes
            main_routes._base_context = reload_context(include_transcripts=True)
            logger.info("Context automatically refreshed after upload")
        except Exception as e:
            logger.warning(f"Failed to auto-refresh context: {e}")
        
        return render_template("upload.html", filename=filename, transcript=transcript, allowed_extensions=allowed_exts)
    
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        return f"An error occurred: {str(e)}", 500


def extract_text_from_pdf(pdf_path):
    """
    Extract text from a PDF file using PyPDF2.
    Falls back to pdfplumber if available.
    
    Args:
        pdf_path: Path to the PDF file
    
    Returns:
        Extracted text as string
    """
    text = ""
    
    # Try PyPDF2 first
    try:
        import PyPDF2
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n\n"
        
        if text.strip():
            logger.info(f"PyPDF2 extracted {len(text)} characters from PDF")
            return text.strip()
    
    except ImportError:
        logger.debug("PyPDF2 not available, trying pdfplumber")
    except Exception as e:
        logger.warning(f"PyPDF2 extraction failed: {e}")
    
    # Try pdfplumber as fallback
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n\n"
        
        if text.strip():
            logger.info(f"pdfplumber extracted {len(text)} characters from PDF")
            return text.strip()
    
    except ImportError:
        logger.error("Neither PyPDF2 nor pdfplumber is installed. Install with: pip install PyPDF2 pdfplumber")
    except Exception as e:
        logger.error(f"pdfplumber extraction failed: {e}")
    
    return text.strip()


def save_pdf_text_to_jsonl(pdf_path, text):
    """
    Save extracted PDF text to data/train.jsonl in the same format as transcripts.
    
    Args:
        pdf_path: Path to the original PDF file
        text: Extracted text content
    """
    import json
    from datetime import datetime
    
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    train_file = os.path.join(data_dir, "train.jsonl")
    
    entry = {
        "text": text,
        "source": os.path.basename(pdf_path),
        "type": "pdf",
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        with open(train_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"PDF text saved to {train_file}")
    except Exception as e:
        logger.error(f"Failed to save PDF text: {e}")


