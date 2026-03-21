import os
import logging
import json

logger = logging.getLogger(__name__)

def load_context(include_transcripts=True):
    """
    Load context from llm-script.txt file and optionally include transcripts.
    
    Args:
        include_transcripts: If True, also load transcripts from data/train.jsonl
    
    Returns:
        Combined context string from llm-script.txt and transcripts
    """
    context_parts = []
    
    # Load base context from llm-script.txt
    possible_paths = [
        "llm-script.txt",  # Current directory
        os.path.join(os.path.dirname(__file__), "..", "..", "llm-script.txt"),  # Project root
        os.path.join(os.getcwd(), "llm-script.txt"),  # Working directory
    ]

    for context_path in possible_paths:
        try:
            abs_path = os.path.abspath(context_path)
            if os.path.exists(abs_path):
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        context_parts.append(content)
                        logger.info(f"Base context loaded from: {abs_path} ({len(content)} characters)")
                        break
        except Exception as e:
            logger.warning(f"Failed to load context from {context_path}: {e}")
            continue
    
    if not context_parts:
        logger.warning("Base context file (llm-script.txt) not found")
    
    # Load transcripts if requested
    if include_transcripts:
        transcripts = load_transcripts()
        if transcripts:
            context_parts.append(transcripts)
            logger.info(f"Transcripts added to context ({len(transcripts)} characters)")
    
    return "\n\n".join(context_parts) if context_parts else ""


def load_transcripts():
    """
    Load all transcripts from data/train.jsonl.
    
    Returns:
        Combined transcript text or empty string if none found
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    transcript_file = os.path.join(base_dir, "data", "train.jsonl")
    
    if not os.path.exists(transcript_file):
        logger.debug(f"No transcript file found at {transcript_file}")
        return ""
    
    transcripts = []
    try:
        with open(transcript_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())
                    if "text" in data and data["text"].strip():
                        transcripts.append(data["text"].strip())
                except json.JSONDecodeError:
                    logger.warning(f"Skipping malformed JSON at line {line_num} in {transcript_file}")
                    continue
        
        if transcripts:
            combined = "\n\n".join(transcripts)
            logger.info(f"Loaded {len(transcripts)} transcript(s) from {transcript_file}")
            return f"=== Uploaded Content Transcripts ===\n\n{combined}"
        
    except Exception as e:
        logger.error(f"Error loading transcripts: {e}")
    
    return ""


def reload_context(include_transcripts=True):
    """
    Reload context dynamically (useful for refreshing after uploads).
    
    Args:
        include_transcripts: If True, also reload transcripts
    
    Returns:
        Fresh combined context string
    """
    return load_context(include_transcripts=include_transcripts)
