package com.intelliverse.whisperyoutube

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

sealed class TranscribeState {
    object Idle : TranscribeState()
    data class Loading(val message: String) : TranscribeState()
    data class Done(val title: String, val transcript: String) : TranscribeState()
    data class Fail(val message: String) : TranscribeState()
}

enum class LinkMode { SINGLE, BATCH, PLAYLIST }

class TranscriptionViewModel(app: Application) : AndroidViewModel(app) {

    private val _state = MutableStateFlow<TranscribeState>(TranscribeState.Idle)
    val state: StateFlow<TranscribeState> = _state

    private val _mode = MutableStateFlow(LinkMode.SINGLE)
    val mode: StateFlow<LinkMode> = _mode

    private val _input = MutableStateFlow("")
    val inputText: StateFlow<String> = _input

    private val _batchResults = MutableStateFlow<List<Pair<String, String>>>(emptyList())
    val batchResults: StateFlow<List<Pair<String, String>>> = _batchResults

    fun setMode(m: LinkMode) { _mode.value = m; reset() }
    fun setInput(t: String)  { _input.value = t }
    fun setSingleUrl(u: String) { _mode.value = LinkMode.SINGLE; _input.value = u }
    fun reset() { _state.value = TranscribeState.Idle; _batchResults.value = emptyList() }

    fun submit() {
        val input = _input.value.trim()
        if (input.isBlank()) {
            _state.value = TranscribeState.Fail("Please enter a YouTube URL")
            return
        }
        when (_mode.value) {
            LinkMode.SINGLE   -> transcribeSingle(input)
            LinkMode.BATCH    -> transcribeBatch(
                input.lines().map { it.trim() }.filter { it.isNotEmpty() }
            )
            LinkMode.PLAYLIST -> _state.value = TranscribeState.Fail("Playlist mode coming soon")
        }
    }

    private fun transcribeSingle(url: String) {
        viewModelScope.launch {
            _state.value = TranscribeState.Loading("Connecting to server…")
            val (transcript, title) = AudioExtractor.transcribeViaServer(url) { msg ->
                _state.value = TranscribeState.Loading(msg)
            }
            if (transcript == null) {
                _state.value = TranscribeState.Fail(
                    "Server could not transcribe this video.\n" +
                            "Note: Server may take 50s to wake up on first request."
                )
            } else {
                _state.value = TranscribeState.Done(title ?: "Video", transcript)
            }
        }
    }

    private fun transcribeBatch(urls: List<String>) {
        if (urls.isEmpty()) {
            _state.value = TranscribeState.Fail("No URLs entered")
            return
        }
        _batchResults.value = emptyList()
        _state.value = TranscribeState.Loading("Processing 0 / ${urls.size}…")

        viewModelScope.launch {
            val results = AudioExtractor.transcribeBatchViaServer(urls) { msg ->
                _state.value = TranscribeState.Loading(msg)
            }
            _batchResults.value = results
            _state.value = TranscribeState.Loading("") // signal done
        }
    }
}