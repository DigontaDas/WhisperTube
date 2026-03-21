import os
from werkzeug.utils import secure_filename
from flask import current_app
import uuid
import subprocess
import re
import logging

logger = logging.getLogger(__name__)

def allowed_file(filename):
    """
    Check if a file has an allowed extension.

    Args:
        filename: Name of the file to check

    Returns:
        bool: True if file extension is allowed, False otherwise
    """
    if not filename:
        return False
    allowed = current_app.config['ALLOWED_EXTENSIONS']
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed

def save_file(file):
    """
    Save an uploaded file with a unique filename.

    Args:
        file: FileStorage object from Flask request

    Returns:
        str: The unique filename of the saved file

    Raises:
        ValueError: If file is invalid or filename is empty
    """
    if not file or not file.filename:
        raise ValueError("Invalid file or filename")

    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)

    original_name = secure_filename(file.filename)
    if not original_name:
        raise ValueError("Invalid filename after sanitization")

    name, ext = os.path.splitext(original_name)
    unique_suffix = uuid.uuid4().hex[:8]
    unique_filename = f"{name}_{unique_suffix}{ext}"
    filepath = os.path.join(upload_folder, unique_filename)

    try:
        file.save(filepath)
        logger.info(f"File saved successfully: {unique_filename}")
    except Exception as e:
        logger.error(f"Failed to save file: {e}")
        raise

    return unique_filename

def download_audio_from_url(url):
    """
    Download audio from a video URL (e.g., YouTube).

    Args:
        url: The URL of the video to download

    Returns:
        str: Path to the downloaded audio file

    Raises:
        ValueError: If URL is invalid
        Exception: If download fails
    """
    if not url or not isinstance(url, str):
        raise ValueError("Invalid URL provided")

    output_dir = "./downloads"
    os.makedirs(output_dir, exist_ok=True)

    try:
        title = get_video_title(url)
        safe_title = sanitize_title(title)
        output_filename = f"{safe_title}.mp3"
        output_path = os.path.join(output_dir, output_filename)

        output_template = os.path.join(output_dir, f"{safe_title}.%(ext)s")
        command = [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "-o", output_template,
            url
        ]

        logger.info(f"Downloading audio from: {url}")
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)

        if not os.path.exists(output_path):
            raise Exception(f"Expected file not found: {output_path}")

        logger.info(f"Audio downloaded successfully: {output_filename}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"Download failed for {url}: {e.stderr.strip()}")
        raise Exception(f"Download failed: {e.stderr.strip()}")
    


def get_video_title(url):
    """
    Get the title of a video from its URL.

    Args:
        url: The URL of the video

    Returns:
        str: The video title

    Raises:
        Exception: If title retrieval fails
    """
    try:
        result = subprocess.run(
            ["yt-dlp", "--get-title", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=30
        )
        title = result.stdout.strip()
        logger.debug(f"Retrieved video title: {title}")
        return title
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout while getting title for: {url}")
        raise Exception("Timeout while retrieving video title")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get title for {url}: {e.stderr.strip()}")
        raise Exception(f"Failed to get title: {e.stderr.strip()}")


def sanitize_title(title):
    """
    Sanitize a title string for use as a filename.

    Args:
        title: The title string to sanitize

    Returns:
        str: Sanitized title safe for use as a filename
    """
    if not title:
        return "untitled"
    # Remove/replace characters that are invalid in filenames
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", title).strip()
    # Limit length to avoid filesystem issues
    return sanitized[:200] if len(sanitized) > 200 else sanitized