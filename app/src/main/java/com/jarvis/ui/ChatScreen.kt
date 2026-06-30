package com.jarvis.ui

import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.jarvis.models.ChatMessage
import com.jarvis.models.MessageRole
import com.jarvis.theme.JarvisColors
import com.jarvis.viewmodel.JarvisViewModel
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

@Composable
fun ChatScreen(viewModel: JarvisViewModel) {
    val messages by viewModel.messages.collectAsState()
    val isProcessing by viewModel.isProcessing.collectAsState()
    var inputText by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()

    // Auto-scroll to bottom when new messages arrive
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.size - 1)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(JarvisColors.bgGradient)
    ) {
        // Messages list
        LazyColumn(
            state = listState,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(vertical = 12.dp),
        ) {
            if (messages.isEmpty()) {
                item {
                    EmptyStateView()
                }
            }

            items(messages, key = { it.id }) { message ->
                ChatBubble(message = message)
            }

            if (isProcessing) {
                item {
                    TypingIndicator()
                }
            }
        }

        // Input bar
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .clip(RoundedCornerShape(24.dp))
                    .background(JarvisColors.bgCard)
                    .padding(horizontal = 20.dp, vertical = 14.dp),
            ) {
                if (inputText.isEmpty()) {
                    Text(
                        text = "Ask Jarvis...",
                        style = TextStyle(
                            color = JarvisColors.textMuted,
                            fontSize = 15.sp,
                        ),
                    )
                }
                BasicTextField(
                    value = inputText,
                    onValueChange = { inputText = it },
                    textStyle = TextStyle(
                        color = JarvisColors.textPrimary,
                        fontSize = 15.sp,
                    ),
                    cursorBrush = SolidColor(JarvisColors.primary),
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = false,
                    maxLines = 4,
                )
            }

            Spacer(modifier = Modifier.width(12.dp))

            IconButton(
                onClick = {
                    if (inputText.isNotBlank()) {
                        viewModel.sendMessage(inputText)
                        inputText = ""
                    }
                },
                modifier = Modifier
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(
                        if (inputText.isNotBlank()) JarvisColors.primary
                        else JarvisColors.bgCard
                    ),
            ) {
                Icon(
                    imageVector = Icons.Default.Send,
                    contentDescription = "Send",
                    tint = if (inputText.isNotBlank()) JarvisColors.bgDark
                    else JarvisColors.textMuted,
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}

@Composable
private fun ChatBubble(message: ChatMessage) {
    val isUser = message.role == MessageRole.USER
    val timeFormat = SimpleDateFormat("HH:mm", Locale.getDefault())

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        if (!isUser) {
            // Jarvis avatar
            Box(
                modifier = Modifier
                    .size(32.dp)
                    .clip(CircleShape)
                    .background(JarvisColors.bgElevated),
                contentAlignment = Alignment.Center,
            ) {
                ArcReactorIndicator(
                    size = 24.dp,
                    isActive = true,
                    isProcessing = false,
                )
            }
            Spacer(modifier = Modifier.width(8.dp))
        }

        Column(
            horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
            modifier = Modifier.widthIn(max = 300.dp),
        ) {
            Surface(
                shape = RoundedCornerShape(
                    topStart = 16.dp,
                    topEnd = 16.dp,
                    bottomStart = if (isUser) 16.dp else 4.dp,
                    bottomEnd = if (isUser) 4.dp else 16.dp,
                ),
                color = if (isUser) JarvisColors.primary.copy(alpha = 0.15f)
                else JarvisColors.bgCard,
                border = if (isUser) null
                else androidx.compose.foundation.BorderStroke(
                    0.5.dp, JarvisColors.borderColor
                ),
            ) {
                Text(
                    text = message.content,
                    style = TextStyle(
                        color = if (isUser) JarvisColors.textPrimary
                        else JarvisColors.textPrimary,
                        fontSize = 14.sp,
                        lineHeight = 20.sp,
                    ),
                    modifier = Modifier.padding(12.dp),
                )
            }

            Text(
                text = timeFormat.format(Date(message.timestamp)),
                style = TextStyle(
                    color = JarvisColors.textMuted,
                    fontSize = 10.sp,
                ),
                modifier = Modifier.padding(top = 4.dp, start = 4.dp, end = 4.dp),
            )
        }
    }
}

@Composable
private fun TypingIndicator() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Start,
    ) {
        Box(
            modifier = Modifier
                .size(32.dp)
                .clip(CircleShape)
                .background(JarvisColors.bgElevated),
            contentAlignment = Alignment.Center,
        ) {
            ArcReactorIndicator(
                size = 24.dp,
                isActive = true,
                isProcessing = true,
            )
        }
        Spacer(modifier = Modifier.width(8.dp))
        Surface(
            shape = RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp),
            color = JarvisColors.bgCard,
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                repeat(3) {
                    Box(
                        modifier = Modifier
                            .size(6.dp)
                            .clip(CircleShape)
                            .background(JarvisColors.primary.copy(alpha = 0.6f)),
                    )
                }
            }
        }
    }
}

@Composable
private fun EmptyStateView() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 80.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        ArcReactorIndicator(
            size = 100.dp,
            isActive = true,
            isProcessing = false,
        )
        Spacer(modifier = Modifier.height(24.dp))
        Text(
            text = "JARVIS",
            style = TextStyle(
                color = JarvisColors.primary,
                fontSize = 28.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 6.sp,
            ),
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = "On-Device AI Assistant",
            style = TextStyle(
                color = JarvisColors.textSecondary,
                fontSize = 14.sp,
            ),
        )
        Spacer(modifier = Modifier.height(32.dp))
        Text(
            text = "Try saying:",
            style = TextStyle(
                color = JarvisColors.textMuted,
                fontSize = 12.sp,
            ),
        )
        Spacer(modifier = Modifier.height(12.dp))

        val suggestions = listOf(
            "Remind me to bring helmet when I leave home",
            "What's my current location?",
            "Am I on my Hunter 350?",
        )
        suggestions.forEach { suggestion ->
            Surface(
                shape = RoundedCornerShape(12.dp),
                color = JarvisColors.bgCard,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 4.dp),
            ) {
                Text(
                    text = "\"$suggestion\"",
                    style = TextStyle(
                        color = JarvisColors.textSecondary,
                        fontSize = 13.sp,
                    ),
                    modifier = Modifier.padding(12.dp),
                )
            }
        }
    }
}
