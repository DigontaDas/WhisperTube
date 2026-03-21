package com.intelliverse.whisperyoutube

import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// ── Colors ────────────────────────────────────────────────────────────────────
private val BgDark      = Color(0xFF0D1117)
private val CardBg      = Color(0xFF161B22)
private val CardBorder  = Color(0xFF30363D)
private val AccentBlue  = Color(0xFF2196F3)
private val AccentGreen = Color(0xFF4CAF50)
private val AccentRed   = Color(0xFFCF6679)
private val TextPrimary = Color(0xFFE6EDF3)
private val TextMuted   = Color(0xFF8B949E)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(viewModel: TranscriptionViewModel) {
    val state       by viewModel.state.collectAsState()
    val mode        by viewModel.mode.collectAsState()
    val inputText   by viewModel.inputText.collectAsState()
    val batchResults by viewModel.batchResults.collectAsState()
    val clipboard   = LocalClipboardManager.current

    val isLoading = state is TranscribeState.Loading &&
            (state as TranscribeState.Loading).message.isNotEmpty()

    Box(Modifier.fillMaxSize().background(BgDark)) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp)
                .padding(top = 56.dp, bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // Header
            AppHeader()

            // Mode tabs
            ModeTabs(selected = mode, onSelect = { viewModel.setMode(it) }, enabled = !isLoading)

            // Input
            InputCard(
                mode = mode,
                value = inputText,
                onValueChange = { viewModel.setInput(it) },
                onPaste = { clipboard.getText()?.text?.let { viewModel.setInput(it) } },
                onClear = { viewModel.setInput("") },
                enabled = !isLoading
            )

            // Submit
            SubmitButton(loading = isLoading) { viewModel.submit() }

            // Results
            when (val s = state) {
                is TranscribeState.Loading -> if (s.message.isNotEmpty()) LoadingCard(s.message)
                is TranscribeState.Done -> SingleResultCard(
                    title = s.title,
                    transcript = s.transcript,
                    onCopy = { clipboard.setText(AnnotatedString(s.transcript)) },
                    onReset = { viewModel.reset() }
                )
                is TranscribeState.Fail -> ErrorCard(s.message) { viewModel.reset() }
                is TranscribeState.Idle -> { /* nothing */ }
            }

            // Batch results (appear progressively)
            if (batchResults.isNotEmpty()) {
                BatchResultsCard(
                    results = batchResults,
                    onCopyAll = {
                        val all = batchResults.joinToString("\n\n---\n\n") {
                            "[ ${it.first} ]\n${it.second}"
                        }
                        clipboard.setText(AnnotatedString(all))
                    },
                    onReset = { viewModel.reset() }
                )
            }
        }
    }
}

@Composable
private fun AppHeader() {
    Row(verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(
            modifier = Modifier.size(42.dp).clip(RoundedCornerShape(11.dp))
                .background(Brush.linearGradient(listOf(AccentBlue, Color(0xFF673AB7)))),
            contentAlignment = Alignment.Center
        ) {
            Icon(Icons.Default.Mic, null, tint = Color.White, modifier = Modifier.size(22.dp))
        }
        Column {
            Text("WhisperTube", color = TextPrimary, fontSize = 22.sp,
                fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp)
            Text("On-device YouTube transcription", color = TextMuted, fontSize = 12.sp)
        }
    }
}

@Composable
private fun ModeTabs(selected: LinkMode, onSelect: (LinkMode) -> Unit, enabled: Boolean) {
    val tabs = listOf(
        Triple(LinkMode.SINGLE, Icons.Default.Link, "Single"),
        Triple(LinkMode.BATCH,  Icons.Default.List, "Batch"),
    )
    Row(
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(CardBg).border(1.dp, CardBorder, RoundedCornerShape(12.dp)).padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        tabs.forEach { (tabMode, icon, label) ->
            val active = selected == tabMode
            Box(
                modifier = Modifier.weight(1f).clip(RoundedCornerShape(9.dp))
                    .background(if (active) AccentBlue else Color.Transparent)
                    .clickable(enabled = enabled) { onSelect(tabMode) }
                    .padding(vertical = 10.dp),
                contentAlignment = Alignment.Center
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Icon(icon, null,
                        tint = if (active) Color.White else TextMuted,
                        modifier = Modifier.size(16.dp))
                    Text(label,
                        color = if (active) Color.White else TextMuted,
                        fontSize = 13.sp,
                        fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal)
                }
            }
        }
    }
}

@Composable
private fun InputCard(
    mode: LinkMode, value: String,
    onValueChange: (String) -> Unit, onPaste: () -> Unit,
    onClear: () -> Unit, enabled: Boolean
) {
    val hint = when (mode) {
        LinkMode.SINGLE   -> "https://youtube.com/watch?v=..."
        LinkMode.BATCH    -> "One URL per line:\nhttps://youtube.com/watch?v=AAA\nhttps://youtu.be/BBB"
        LinkMode.PLAYLIST -> "https://youtube.com/playlist?list=..."
    }
    GlassCard {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Default.VideoLibrary, null, tint = Color.Red,
                    modifier = Modifier.size(18.dp))
                Text(
                    if (mode == LinkMode.BATCH) "YouTube URLs — one per line"
                    else "YouTube URL",
                    color = TextMuted, fontSize = 13.sp
                )
            }
            OutlinedTextField(
                value = value, onValueChange = onValueChange,
                placeholder = { Text(hint, color = TextMuted, fontSize = 12.sp) },
                modifier = Modifier.fillMaxWidth(),
                enabled = enabled,
                singleLine = mode == LinkMode.SINGLE,
                minLines = if (mode == LinkMode.BATCH) 4 else 1,
                maxLines = if (mode == LinkMode.BATCH) 8 else 1,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction = if (mode == LinkMode.BATCH) ImeAction.Default else ImeAction.Done
                ),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary,
                    focusedBorderColor = AccentBlue, unfocusedBorderColor = CardBorder,
                    cursorColor = AccentBlue,
                    focusedContainerColor = BgDark, unfocusedContainerColor = BgDark,
                ),
                shape = RoundedCornerShape(10.dp)
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = onPaste, enabled = enabled, modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(8.dp),
                    border = androidx.compose.foundation.BorderStroke(1.dp, CardBorder),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = TextMuted)
                ) {
                    Icon(Icons.Default.ContentPaste, null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(6.dp)); Text("Paste", fontSize = 13.sp)
                }
                if (value.isNotEmpty()) {
                    OutlinedButton(
                        onClick = onClear, enabled = enabled, modifier = Modifier.weight(1f),
                        shape = RoundedCornerShape(8.dp),
                        border = androidx.compose.foundation.BorderStroke(1.dp, CardBorder),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = TextMuted)
                    ) {
                        Icon(Icons.Default.Clear, null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp)); Text("Clear", fontSize = 13.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun SubmitButton(loading: Boolean, onClick: () -> Unit) {
    Button(
        onClick = onClick, enabled = !loading,
        modifier = Modifier.fillMaxWidth().height(52.dp),
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = AccentBlue,
            disabledContainerColor = AccentBlue.copy(alpha = 0.4f)
        )
    ) {
        if (loading) {
            CircularProgressIndicator(Modifier.size(20.dp), color = Color.White, strokeWidth = 2.dp)
            Spacer(Modifier.width(10.dp))
            Text("Processing…", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
        } else {
            Icon(Icons.Default.Mic, null, tint = Color.White, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(10.dp))
            Text("Transcribe", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
        }
    }
}

@Composable
private fun LoadingCard(message: String) {
    GlassCard {
        Column(Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            CircularProgressIndicator(color = AccentBlue, strokeWidth = 3.dp)
            Text(message, color = TextPrimary, fontSize = 14.sp,
                textAlign = TextAlign.Center, lineHeight = 20.sp)
        }
    }
}

@Composable
private fun SingleResultCard(
    title: String, transcript: String,
    onCopy: () -> Unit, onReset: () -> Unit
) {
    GlassCard {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                        Box(Modifier.size(7.dp).clip(RoundedCornerShape(50)).background(AccentGreen))
                        Text("Done", color = AccentGreen, fontSize = 11.sp,
                            fontWeight = FontWeight.SemiBold)
                    }
                    if (title.isNotBlank()) {
                        Spacer(Modifier.height(4.dp))
                        Text(title, color = TextPrimary, fontSize = 14.sp,
                            fontWeight = FontWeight.SemiBold,
                            maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
                Row {
                    IconButton(onClick = onCopy) {
                        Icon(Icons.Default.ContentCopy, null, tint = TextMuted,
                            modifier = Modifier.size(20.dp))
                    }
                    IconButton(onClick = onReset) {
                        Icon(Icons.Default.Refresh, null, tint = TextMuted,
                            modifier = Modifier.size(20.dp))
                    }
                }
            }
            HorizontalDivider(color = CardBorder)
            Text(transcript, color = TextPrimary, fontSize = 14.sp, lineHeight = 22.sp)
        }
    }
}

@Composable
private fun BatchResultsCard(
    results: List<Pair<String, String>>,
    onCopyAll: () -> Unit,
    onReset: () -> Unit
) {
    GlassCard {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically) {
                Row(verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Box(Modifier.size(7.dp).clip(RoundedCornerShape(50)).background(AccentGreen))
                    Text("${results.size} result(s)", color = AccentGreen,
                        fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                }
                Row {
                    IconButton(onClick = onCopyAll) {
                        Icon(Icons.Default.ContentCopy, null, tint = TextMuted,
                            modifier = Modifier.size(20.dp))
                    }
                    IconButton(onClick = onReset) {
                        Icon(Icons.Default.Refresh, null, tint = TextMuted,
                            modifier = Modifier.size(20.dp))
                    }
                }
            }
            results.forEachIndexed { i, (title, transcript) ->
                if (i > 0) HorizontalDivider(color = CardBorder)
                var expanded by remember(i) { mutableStateOf(false) }
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(Modifier.fillMaxWidth().clickable { expanded = !expanded },
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically) {
                        Text(title, color = AccentBlue, fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.weight(1f),
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Icon(
                            if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                            null, tint = TextMuted, modifier = Modifier.size(18.dp)
                        )
                    }
                    AnimatedVisibility(visible = expanded) {
                        Text(transcript, color = TextPrimary,
                            fontSize = 13.sp, lineHeight = 20.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun ErrorCard(message: String, onRetry: () -> Unit) {
    GlassCard(borderColor = AccentRed.copy(alpha = 0.4f)) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Default.ErrorOutline, null, tint = AccentRed,
                    modifier = Modifier.size(20.dp))
                Text("Error", color = AccentRed, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold)
            }
            Text(message, color = TextPrimary, fontSize = 13.sp, lineHeight = 20.sp)
            TextButton(onClick = onRetry) {
                Text("Try again", color = AccentBlue, fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun GlassCard(
    borderColor: Color = CardBorder,
    content: @Composable ColumnScope.() -> Unit
) {
    Column(
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp))
            .background(CardBg).border(1.dp, borderColor, RoundedCornerShape(14.dp))
            .padding(16.dp),
        content = content
    )
}