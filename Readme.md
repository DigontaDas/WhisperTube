# WhisperTube

YouTube transcription app — Android + Flask server.

## Architecture
- **Android app**: Sends YouTube URL to server
- **Server (Render)**: Gets transcript via youtube-transcript-api or yt-dlp + Groq Whisper
- **Result**: Transcript displayed on phone

## Server
Flask API deployed on Render.
- `GET /api/health` — health check
- `POST /api/transcribe` — transcribe a YouTube URL

## Android
Kotlin/Jetpack Compose app that sends URLs to the server and displays transcripts.