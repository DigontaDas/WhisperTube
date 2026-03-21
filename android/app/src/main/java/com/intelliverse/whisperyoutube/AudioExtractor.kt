package com.intelliverse.whisperyoutube

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object AudioExtractor {

    private const val TAG = "AudioExtractor"
    private const val SERVER_URL = "https://virtualclone-deploy.onrender.com"

    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(300, TimeUnit.SECONDS) // 5 min — yt-dlp + transcription takes time
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    fun extractVideoId(url: String): String? {
        val patterns = listOf(
            Regex("""(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})"""),
            Regex("""youtube\.com/shorts/([a-zA-Z0-9_-]{11})"""),
            Regex("""youtube\.com/embed/([a-zA-Z0-9_-]{11})""")
        )
        for (p in patterns) {
            val m = p.find(url)
            if (m != null) return m.groupValues[1]
        }
        return null
    }

    /**
     * Send YouTube URL to server → get back transcript.
     * Server handles yt-dlp + Groq Whisper.
     * Phone just displays the result.
     */
    suspend fun transcribeViaServer(
        url: String,
        onProgress: (String) -> Unit = {}
    ): Pair<String?, String?> = withContext(Dispatchers.IO) {
        try {
            // First wake up the server (Render free tier sleeps)
            onProgress("Waking up server…")
            Log.d(TAG, "Pinging server...")
            try {
                val ping = Request.Builder()
                    .url("$SERVER_URL/api/health")
                    .build()
                val pingResp = client.newCall(ping).execute()
                Log.d(TAG, "Server ping: ${pingResp.code}")
            } catch (e: Exception) {
                Log.w(TAG, "Ping failed: ${e.message}")
            }

            onProgress("Sending to server for transcription…")
            Log.d(TAG, "Sending URL to server: $url")

            val body = JSONObject().apply {
                put("type", "single")
                put("url", url)
            }.toString()

            val request = Request.Builder()
                .url("$SERVER_URL/api/transcribe")
                .post(body.toRequestBody("application/json".toMediaType()))
                .addHeader("Content-Type", "application/json")
                .build()

            val response = client.newCall(request).execute()
            val responseBody = response.body?.string()
            Log.d(TAG, "Server response: ${response.code}, body: ${responseBody?.take(200)}")

            if (!response.isSuccessful || responseBody == null) {
                Log.e(TAG, "Server error: ${response.code}")
                return@withContext Pair(null, null)
            }

            val json = JSONObject(responseBody)

            // Handle both response formats
            val transcript = when {
                json.has("transcript") -> json.getString("transcript")
                json.has("transcription") -> json.getString("transcription")
                json.has("text") -> json.getString("text")
                json.has("result") -> json.getString("result")
                else -> {
                    Log.e(TAG, "Unknown response format: $responseBody")
                    null
                }
            }

            val title = when {
                json.has("title") -> json.optString("title", "Video")
                json.has("video_title") -> json.optString("video_title", "Video")
                else -> "Video"
            }

            Log.d(TAG, "Transcript received, length=${transcript?.length}, title=$title")
            Pair(transcript, title)

        } catch (e: Exception) {
            Log.e(TAG, "Server request failed: ${e.message}")
            Pair(null, null)
        }
    }

    /**
     * Batch: send multiple URLs, get back list of transcripts
     */
    suspend fun transcribeBatchViaServer(
        urls: List<String>,
        onProgress: (String) -> Unit = {}
    ): List<Pair<String, String>> = withContext(Dispatchers.IO) {
        val results = mutableListOf<Pair<String, String>>()
        urls.forEachIndexed { idx, url ->
            onProgress("${idx + 1}/${urls.size}: Transcribing…")
            val (transcript, title) = transcribeViaServer(url)
            results.add(Pair(
                title ?: "Video ${idx + 1}",
                transcript ?: "[Error] Failed to transcribe"
            ))
        }
        results
    }
}