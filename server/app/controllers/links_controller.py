from flask import render_template, current_app
import subprocess
from app.services.file_service import download_audio_from_url
from app.services.transcribe_service import transcribe_audio
import os
import logging

logger = logging.getLogger(__name__)

def handle_links(urls, link_type='single'):
    """
    Handles the submission of links for audio transcription.
    Supports both single and batch link submissions.
    """
    try:
        transcript = ''

        if link_type == 'single':
            transcript = handle_single_link(urls[0])
        elif link_type == 'playlist':
            transcript = handle_playlist_link(urls[0])
        elif link_type == 'batch':
            logger.info(f"Processing batch links: {len(urls)} URLs")
            transcript = handle_links_batch_sync(urls)

        return render_template('links.html', transcript=transcript)
    except Exception as e:
        logger.error(f"Error handling links: {e}")
        return render_template('links.html', error=str(e))
    
def handle_links_batch_sync(urls):
    """Process multiple URLs synchronously"""
    results = []
    for idx, url in enumerate(urls, 1):
        try:
            logger.info(f"Processing {idx}/{len(urls)}: {url}")
            audio_path = download_audio_from_url(url)

            if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1024:
                logger.warning(f"Invalid audio file for {url}")
                results.append(f"[Error: audio file invalid for {url}]")
                continue

            text = transcribe_audio(audio_path)
            if not text:
                logger.warning(f"Transcription failed for {url}")
                results.append(f"[Error: transcription failed for {url}]")
                continue

            results.append(f"--- Transcription for {url} ---\n{text}")
            logger.info(f"Successfully processed {url}")
        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            results.append(f"[Error processing {url}]: {str(e)}")

    return "\n\n".join(results)


def handle_single_link(url):
    """Process a single link"""
    try:
        logger.info(f"Processing single link: {url}")
        audio_path = download_audio_from_url(url)
        transcript = transcribe_audio(audio_path)
        logger.info("Successfully processed single link")
        return transcript
    except Exception as e:
        logger.error(f"Error processing single link: {e}")
        raise Exception(str(e))

def handle_playlist_link(channel_url):
    """Process a playlist of videos"""
    max_videos = current_app.config['MAX_VIDEOS']

    try:
        logger.info(f"Processing playlist: {channel_url} (max {max_videos} videos)")
        command = ["yt-dlp", "--flat-playlist", "--get-id", channel_url]
        if max_videos:
            command += ["--playlist-end", str(max_videos)]

        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        video_ids = result.stdout.strip().splitlines()
        logger.info(f"Found {len(video_ids)} videos in playlist")

        transcripts = []
        for idx, vid in enumerate(video_ids, 1):
            vid = vid.strip()
            if not vid:
                continue

            # Build URL
            if vid.startswith("http://") or vid.startswith("https://"):
                url = vid
            else:
                url = f"https://www.youtube.com/watch?v={vid}"

            try:
                logger.info(f"Processing video {idx}/{len(video_ids)}: {url}")
                audio_path = download_audio_from_url(url)
                text = transcribe_audio(audio_path)
                if text:
                    transcripts.append(text)
            except Exception as e:
                logger.error(f"Error processing video {url}: {e}")
                transcripts.append(f"[Error: {str(e)}]")

        return '\n\n'.join(transcripts)
    except Exception as e:
        logger.error(f"Error processing playlist: {e}")
        raise Exception(str(e))