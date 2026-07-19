package com.jarvis.edge.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.outlined.Menu
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.alpha
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jarvis.edge.data.repository.ContextRepository
import com.jarvis.edge.data.repository.FirestoreRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import androidx.compose.runtime.rememberCoroutineScope


private const val EMPTY_THREAD_ID = "_no_selected_thread_"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    uid: String,
    firestoreRepository: FirestoreRepository,
    contextRepository: ContextRepository,
    modifier: Modifier = Modifier
) {
    val scope = rememberCoroutineScope()
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    val threads by firestoreRepository.getChatThreads(uid).collectAsState(initial = emptyList())
    var selectedThreadId by rememberSaveable { mutableStateOf<String?>(null) }
    var draft by rememberSaveable { mutableStateOf("") }
    var isSending by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var renameDialogOpen by remember { mutableStateOf(false) }
    var deleteDialogOpen by remember { mutableStateOf(false) }
    var menuExpanded by remember { mutableStateOf(false) }

    LaunchedEffect(threads) {
        if (selectedThreadId !in threads.map { it["id"]?.toString() }) {
            selectedThreadId = threads.firstOrNull()?.get("id")?.toString()
        }
    }

    val selectedThread = threads.firstOrNull { it["id"]?.toString() == selectedThreadId }
    val messages by firestoreRepository.getChatMessages(
        uid,
        selectedThreadId ?: EMPTY_THREAD_ID
    ).collectAsState(initial = emptyList())

    val listState = rememberLazyListState()

    // Auto-scroll to bottom when new messages arrive
    LaunchedEffect(messages.size, isSending) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(
                if (isSending) messages.size else messages.size - 1
            )
        }
    }

    suspend fun createConversation(): String? {
        val created = firestoreRepository.createChatThread(uid).getOrElse {
            errorMessage = it.message ?: "Couldn't create a new chat"
            return null
        }
        val threadId = created["id"]?.toString() ?: return null
        selectedThreadId = threadId
        drawerState.close()
        return threadId
    }

    if (renameDialogOpen && selectedThreadId != null) {
        var title by remember(selectedThreadId) {
            mutableStateOf(selectedThread?.get("title")?.toString().orEmpty())
        }
        AlertDialog(
            onDismissRequest = { renameDialogOpen = false },
            title = { Text("Rename chat") },
            text = {
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    label = { Text("Chat title") },
                    singleLine = true
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        if (title.isBlank()) return@TextButton
                        val threadId = selectedThreadId ?: return@TextButton
                        scope.launch {
                            firestoreRepository.renameChatThread(uid, threadId, title)
                                .onFailure { errorMessage = it.message ?: "Couldn't rename chat" }
                            renameDialogOpen = false
                        }
                    }
                ) { Text("Save") }
            },
            dismissButton = {
                TextButton(onClick = { renameDialogOpen = false }) { Text("Cancel") }
            }
        )
    }

    if (deleteDialogOpen && selectedThreadId != null) {
        AlertDialog(
            onDismissRequest = { deleteDialogOpen = false },
            title = { Text("Delete this chat?") },
            text = { Text("This removes the conversation and all of its messages from your workspace.") },
            confirmButton = {
                TextButton(
                    onClick = {
                        val threadId = selectedThreadId ?: return@TextButton
                        scope.launch {
                            firestoreRepository.deleteChatThread(uid, threadId)
                                .onFailure { errorMessage = it.message ?: "Couldn't delete chat" }
                            selectedThreadId = null
                            deleteDialogOpen = false
                        }
                    }
                ) { Text("Delete", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { deleteDialogOpen = false }) { Text("Cancel") }
            }
        )
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(16.dp)
                ) {
                    Text("Chats", style = MaterialTheme.typography.headlineSmall)
                    Spacer(Modifier.height(12.dp))
                    Button(
                        onClick = { scope.launch { createConversation() } },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("+ New chat") }
                    Spacer(Modifier.height(16.dp))
                    if (threads.isEmpty()) {
                        Text(
                            "Start a chat to keep a separate conversation for each topic.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    } else {
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            items(threads, key = { it["id"]?.toString().orEmpty() }) { thread ->
                                val threadId = thread["id"]?.toString().orEmpty()
                                val isSelected = threadId == selectedThreadId
                                ThreadRow(
                                    title = thread["title"]?.toString()?.ifBlank { "New chat" } ?: "New chat",
                                    selected = isSelected,
                                    onClick = {
                                        selectedThreadId = threadId
                                        scope.launch { drawerState.close() }
                                    }
                                )
                            }
                        }
                    }
                }
            }
        }
    ) {
        Scaffold(
            modifier = modifier,
            topBar = {
                TopAppBar(
                    title = {
                        Text(
                            selectedThread?.get("title")?.toString()?.ifBlank { "New chat" } ?: "New chat",
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawerState.open() } }) {
                            Icon(Icons.Outlined.Menu, contentDescription = "Chats")
                        }
                    },
                    actions = {
                        IconButton(onClick = { menuExpanded = true }) {
                            Icon(Icons.Outlined.MoreVert, contentDescription = "Chat options")
                        }
                        DropdownMenu(
                            expanded = menuExpanded,
                            onDismissRequest = { menuExpanded = false }
                        ) {
                            DropdownMenuItem(
                                text = { Text("New chat") },
                                onClick = {
                                    menuExpanded = false
                                    scope.launch { createConversation() }
                                }
                            )
                            if (selectedThreadId != null) {
                                DropdownMenuItem(
                                    text = { Text("Rename") },
                                    onClick = {
                                        menuExpanded = false
                                        renameDialogOpen = true
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Delete") },
                                    onClick = {
                                        menuExpanded = false
                                        deleteDialogOpen = true
                                    }
                                )
                            }
                        }
                    }
                )
            }
        ) { innerPadding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding)
            ) {
                if (selectedThreadId == null) {
                    EmptyChatState(onNewChat = { scope.launch { createConversation() } })
                } else {
                    LazyColumn(
                        modifier = Modifier.weight(1f),
                        state = listState,
                        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        if (messages.isEmpty()) {
                            item {
                                Text(
                                    "Ask anything. Jarvis can help manage tasks, reminders, notes, and your current context.",
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    style = MaterialTheme.typography.bodyMedium,
                                    modifier = Modifier.padding(top = 24.dp)
                                )
                            }
                        }
                        items(messages, key = { it["id"]?.toString().orEmpty() }) { message ->
                            ChatMessageBubble(message = message)
                        }
                        if (isSending) {
                            item(key = "loading_bubble") {
                                ProcessingMessageBubble()
                            }
                        }
                    }
                }

                errorMessage?.let { error ->
                    Text(
                        text = error,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                    )
                }

                // ── Polished input bar ──────────────────────────────────
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    tonalElevation = 2.dp
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.Bottom
                    ) {
                        Surface(
                            modifier = Modifier.weight(1f),
                            shape = RoundedCornerShape(24.dp),
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
                        ) {
                            TextField(
                                value = draft,
                                onValueChange = { draft = it },
                                placeholder = {
                                    Text(
                                        "Message Jarvis",
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                                    )
                                },
                                modifier = Modifier.fillMaxWidth(),
                                enabled = !isSending,
                                maxLines = 4,
                                colors = TextFieldDefaults.colors(
                                    focusedContainerColor = Color.Transparent,
                                    unfocusedContainerColor = Color.Transparent,
                                    disabledContainerColor = Color.Transparent,
                                    focusedIndicatorColor = Color.Transparent,
                                    unfocusedIndicatorColor = Color.Transparent,
                                    disabledIndicatorColor = Color.Transparent,
                                    cursorColor = MaterialTheme.colorScheme.primary
                                ),
                                textStyle = MaterialTheme.typography.bodyLarge
                            )
                        }
                        Spacer(Modifier.width(8.dp))
                        val canSend = draft.isNotBlank() && !isSending
                        Surface(
                            modifier = Modifier.size(44.dp),
                            shape = CircleShape,
                            color = if (canSend) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f),
                            onClick = sendButton@{
                                if (!canSend) return@sendButton
                                val command = draft.trim()
                                scope.launch {
                                    errorMessage = null
                                    isSending = true
                                    val shouldNameThread = selectedThread?.get("title")
                                        ?.toString()
                                        ?.equals("New chat", ignoreCase = true) != false
                                    val threadId = selectedThreadId ?: createConversation()
                                    if (threadId == null) {
                                        isSending = false
                                        return@launch
                                    }
                                    if (shouldNameThread) {
                                        firestoreRepository.renameChatThread(
                                            uid,
                                            threadId,
                                            command.take(48)
                                        )
                                    }
                                    contextRepository.executeCommand(command, threadId)
                                        .onFailure { errorMessage = it.message ?: "Jarvis couldn't reply" }
                                    if (errorMessage == null) draft = ""
                                    isSending = false
                                }
                            }
                        ) {
                            Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
                                if (isSending) {
                                    Text(
                                        "…",
                                        color = MaterialTheme.colorScheme.onPrimary,
                                        style = MaterialTheme.typography.titleMedium
                                    )
                                } else {
                                    Icon(
                                        Icons.Filled.ArrowUpward,
                                        contentDescription = "Send",
                                        tint = if (canSend) MaterialTheme.colorScheme.onPrimary
                                               else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f),
                                        modifier = Modifier.size(22.dp)
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ThreadRow(title: String, selected: Boolean, onClick: () -> Unit) {
    val container = if (selected) {
        MaterialTheme.colorScheme.secondaryContainer
    } else {
        MaterialTheme.colorScheme.surface
    }
    Text(
        text = title,
        maxLines = 2,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(container)
            .clickable(onClick = onClick)
            .padding(12.dp),
        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal
    )
}

@Composable
private fun EmptyChatState(onNewChat: () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(32.dp)) {
            Text("Start a new conversation", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.height(8.dp))
            Text(
                "Keep work, travel, and personal questions in separate chats.",
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.height(16.dp))
            Button(onClick = onNewChat) { Text("New chat") }
        }
    }
}

@Composable
private fun ChatMessageBubble(
    message: Map<String, Any>
) {
    val isUser = message["role"]?.toString() == "user"
    val content = message["content"]?.toString().orEmpty()
    val screenWidth = LocalConfiguration.current.screenWidthDp.dp
    var showPipelineDetails by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start
    ) {
        // Role label
        Text(
            text = if (isUser) "You" else "Jarvis",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
            modifier = Modifier.padding(bottom = 4.dp, start = 4.dp, end = 4.dp)
        )
        
        SelectionContainer {
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = if (isUser) {
                        MaterialTheme.colorScheme.primaryContainer
                    } else {
                        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.7f)
                    }
                ),
                shape = RoundedCornerShape(
                    topStart = 20.dp,
                    topEnd = 20.dp,
                    bottomStart = if (isUser) 20.dp else 6.dp,
                    bottomEnd = if (isUser) 6.dp else 20.dp
                ),
                elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
                modifier = Modifier.widthIn(max = screenWidth * 0.85f)
            ) {
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Text(
                        text = content,
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (isUser) MaterialTheme.colorScheme.onPrimaryContainer
                        else MaterialTheme.colorScheme.onSurface
                    )

                    if (!isUser) {
                        Spacer(Modifier.height(8.dp))
                        // Expandable Pipeline Feedback pill (Gemini / Claude style)
                        Surface(
                            onClick = { showPipelineDetails = !showPipelineDetails },
                            shape = RoundedCornerShape(12.dp),
                            color = MaterialTheme.colorScheme.surface.copy(alpha = 0.6f),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(
                                        Icons.Default.CheckCircle,
                                        contentDescription = null,
                                        tint = MaterialTheme.colorScheme.primary,
                                        modifier = Modifier.size(14.dp)
                                    )
                                    Spacer(Modifier.width(6.dp))
                                    Text(
                                        text = "Pipeline Feedback (5 steps)",
                                        style = MaterialTheme.typography.labelMedium,
                                        fontWeight = FontWeight.Medium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                                Icon(
                                    if (showPipelineDetails) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                                    contentDescription = "Toggle pipeline details",
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                        }

                        AnimatedVisibility(
                            visible = showPipelineDetails,
                            enter = expandVertically(),
                            exit = shrinkVertically()
                        ) {
                            Column(
                                modifier = Modifier
                                    .padding(top = 8.dp)
                                    .background(
                                        MaterialTheme.colorScheme.surface.copy(alpha = 0.4f),
                                        RoundedCornerShape(8.dp)
                                    )
                                    .padding(10.dp),
                                verticalArrangement = Arrangement.spacedBy(6.dp)
                            ) {
                                PipelineStepItem(stepNumber = 1, title = "📡 Context Grounding", detail = "GPS & physical telemetry resolved", isDone = true)
                                PipelineStepItem(stepNumber = 2, title = "🎯 Intent Router", detail = "LangGraph state machine routed user command", isDone = true)
                                PipelineStepItem(stepNumber = 3, title = "🤖 Tier 2 LLM Orchestrator", detail = "OpenRouter constructed function call schema", isDone = true)
                                PipelineStepItem(stepNumber = 4, title = "⚙️ Tool Validation & Execution", detail = "Allowlisted tools executed & Firestore updated", isDone = true)
                                PipelineStepItem(stepNumber = 5, title = "✨ Response Synthesis", detail = "Natural language answer synthesized", isDone = true)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PipelineStepItem(
    stepNumber: Int,
    title: String,
    detail: String,
    isDone: Boolean
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(
            imageVector = Icons.Default.CheckCircle,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(12.dp)
        )
        Spacer(Modifier.width(8.dp))
        Column {
            Text(
                text = title,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                text = detail,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun ProcessingMessageBubble() {
    var activeStep by remember { mutableStateOf(1) }

    LaunchedEffect(Unit) {
        val delays = listOf(700L, 900L, 1100L, 1000L)
        for (i in 1..4) {
            delay(delays[i - 1])
            activeStep = i + 1
        }
    }

    val pipelineSteps = listOf(
        "📡 Context Grounding" to "Resolving GPS location & physical telemetry...",
        "🎯 Intent Router" to "Classifying command scope in LangGraph...",
        "🤖 Tier 2 LLM Orchestrator" to "Invoking OpenRouter model for tool planning...",
        "⚙️ Tool Execution" to "Validating & running background tools...",
        "✨ Response Synthesis" to "Synthesizing final response..."
    )

    val screenWidth = LocalConfiguration.current.screenWidthDp.dp

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalAlignment = Alignment.Start
    ) {
        Text(
            text = "Jarvis Pipeline Feedback",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.primary,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(bottom = 4.dp, start = 4.dp)
        )

        SelectionContainer {
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.85f)
                ),
                shape = RoundedCornerShape(
                    topStart = 20.dp,
                    topEnd = 20.dp,
                    bottomStart = 6.dp,
                    bottomEnd = 20.dp
                ),
                elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
                modifier = Modifier.widthIn(max = screenWidth * 0.88f)
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    // Header with animated pulsing live indicator
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            val infiniteTransition = rememberInfiniteTransition(label = "pulse")
                            val alpha by infiniteTransition.animateFloat(
                                initialValue = 0.3f,
                                targetValue = 1.0f,
                                animationSpec = infiniteRepeatable(
                                    animation = keyframes {
                                        durationMillis = 800
                                        0.3f at 0
                                        1.0f at 400
                                        0.3f at 800
                                    },
                                    repeatMode = RepeatMode.Restart
                                ),
                                label = "alpha"
                            )
                            Box(
                                modifier = Modifier
                                    .size(8.dp)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.primary)
                                    .alpha(alpha)
                            )
                            Spacer(Modifier.width(8.dp))
                            Text(
                                text = "Pipeline active (Stage $activeStep/5)",
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Text(
                            text = "${activeStep * 20}%",
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }

                    // Simple progress line
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(3.dp)
                            .clip(RoundedCornerShape(2.dp))
                            .background(MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f))
                    ) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth(fraction = activeStep / 5f)
                                .height(3.dp)
                                .clip(RoundedCornerShape(2.dp))
                                .background(MaterialTheme.colorScheme.primary)
                        )
                    }

                    // Steps feedback feed
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        pipelineSteps.forEachIndexed { index, (stepTitle, stepDesc) ->
                            val stepNum = index + 1
                            val isDone = stepNum < activeStep
                            val isCurrent = stepNum == activeStep

                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(vertical = 1.dp)
                            ) {
                                if (isDone) {
                                    Icon(
                                        imageVector = Icons.Default.CheckCircle,
                                        contentDescription = null,
                                        tint = MaterialTheme.colorScheme.primary,
                                        modifier = Modifier.size(14.dp)
                                    )
                                } else if (isCurrent) {
                                    val infiniteTransition = rememberInfiniteTransition(label = "dotPulse")
                                    val scaleAlpha by infiniteTransition.animateFloat(
                                        initialValue = 0.4f,
                                        targetValue = 1.0f,
                                        animationSpec = infiniteRepeatable(
                                            animation = keyframes {
                                                durationMillis = 600
                                                0.4f at 0
                                                1.0f at 300
                                                0.4f at 600
                                            },
                                            repeatMode = RepeatMode.Restart
                                        ),
                                        label = "dotAlpha"
                                    )
                                    Box(
                                        modifier = Modifier
                                            .size(10.dp)
                                            .clip(CircleShape)
                                            .background(MaterialTheme.colorScheme.primary)
                                            .alpha(scaleAlpha)
                                    )
                                } else {
                                    Box(
                                        modifier = Modifier
                                            .size(8.dp)
                                            .clip(CircleShape)
                                            .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f))
                                    )
                                }

                                Spacer(Modifier.width(10.dp))

                                Column {
                                    Text(
                                        text = stepTitle,
                                        style = MaterialTheme.typography.labelSmall,
                                        fontWeight = if (isCurrent) FontWeight.Bold else if (isDone) FontWeight.Medium else FontWeight.Normal,
                                        color = if (isCurrent) MaterialTheme.colorScheme.primary
                                                else if (isDone) MaterialTheme.colorScheme.onSurface
                                                else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
                                    )
                                    if (isCurrent) {
                                        Text(
                                            text = stepDesc,
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

