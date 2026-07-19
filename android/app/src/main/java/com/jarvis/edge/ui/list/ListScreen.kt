package com.jarvis.edge.ui.list

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.outlined.EventNote
import androidx.compose.material.icons.outlined.TaskAlt
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.jarvis.edge.data.repository.FirestoreRepository
import com.jarvis.edge.ui.theme.FitBlue
import com.jarvis.edge.ui.theme.FitBlueContainer
import com.jarvis.edge.ui.theme.FitGreen
import com.jarvis.edge.ui.theme.FitGreenContainer
import kotlinx.coroutines.launch

private data class PlannerTab(
    val title: String,
    val icon: ImageVector,
    val accentColor: Color,
    val accentContainer: Color
)

private sealed interface DialogMode {
    data object Closed : DialogMode
    data class AddTask(val dummy: Unit = Unit) : DialogMode
    data class EditTask(val id: String, val currentTitle: String, val currentDueDate: String, val currentTriggerPlace: String) : DialogMode
    data class AddNote(val dummy: Unit = Unit) : DialogMode
    data class EditNote(val id: String, val currentContent: String) : DialogMode
    data class ConfirmDelete(val collection: String, val id: String, val label: String) : DialogMode
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ListScreen(
    uid: String,
    firestoreRepository: FirestoreRepository,
    onNavigateBack: () -> Unit = {},
    showTopBar: Boolean = true,
    modifier: Modifier = Modifier
) {
    val scope = rememberCoroutineScope()
    var selectedTab by remember { mutableIntStateOf(0) }
    val tabs = listOf(
        PlannerTab("Tasks", Icons.Outlined.TaskAlt, FitBlue, FitBlueContainer),
        PlannerTab("Notes", Icons.Outlined.EventNote, FitGreen, FitGreenContainer)
    )

    val tasks by firestoreRepository.getTasks(uid).collectAsState(initial = emptyList())
    val notes by firestoreRepository.getNotes(uid).collectAsState(initial = emptyList())

    var dialogMode by remember { mutableStateOf<DialogMode>(DialogMode.Closed) }

    // ── Dialogs ─────────────────────────────────────────────────────

    when (val mode = dialogMode) {
        DialogMode.Closed -> { /* nothing */ }

        is DialogMode.AddTask -> {
            TaskDialog(
                title = "New Task",
                initialTitle = "",
                initialDueDate = "",
                initialTriggerPlace = "",
                onDismiss = { dialogMode = DialogMode.Closed },
                onConfirm = { titleVal, dueDateVal, triggerPlaceVal ->
                    scope.launch { firestoreRepository.createTask(uid, titleVal, dueDateVal, triggerPlaceVal) }
                    dialogMode = DialogMode.Closed
                }
            )
        }

        is DialogMode.EditTask -> {
            TaskDialog(
                title = "Edit Task",
                initialTitle = mode.currentTitle,
                initialDueDate = mode.currentDueDate,
                initialTriggerPlace = mode.currentTriggerPlace,
                onDismiss = { dialogMode = DialogMode.Closed },
                onConfirm = { titleVal, dueDateVal, triggerPlaceVal ->
                    scope.launch { firestoreRepository.updateTask(uid, mode.id, titleVal, dueDateVal, triggerPlaceVal) }
                    dialogMode = DialogMode.Closed
                }
            )
        }

        is DialogMode.AddNote -> {
            SingleFieldDialog(
                title = "New Note",
                fieldLabel = "Content",
                initialValue = "",
                singleLine = false,
                onDismiss = { dialogMode = DialogMode.Closed },
                onConfirm = { value ->
                    scope.launch { firestoreRepository.createNote(uid, value) }
                    dialogMode = DialogMode.Closed
                }
            )
        }

        is DialogMode.EditNote -> {
            SingleFieldDialog(
                title = "Edit Note",
                fieldLabel = "Content",
                initialValue = mode.currentContent,
                singleLine = false,
                onDismiss = { dialogMode = DialogMode.Closed },
                onConfirm = { value ->
                    scope.launch { firestoreRepository.updateNote(uid, mode.id, value) }
                    dialogMode = DialogMode.Closed
                }
            )
        }

        is DialogMode.ConfirmDelete -> {
            AlertDialog(
                onDismissRequest = { dialogMode = DialogMode.Closed },
                title = { Text("Delete ${mode.label}?") },
                text = { Text("This cannot be undone.") },
                confirmButton = {
                    TextButton(onClick = {
                        scope.launch {
                            when (mode.collection) {
                                "tasks" -> firestoreRepository.deleteTask(uid, mode.id)
                                "notes" -> firestoreRepository.deleteNote(uid, mode.id)
                            }
                        }
                        dialogMode = DialogMode.Closed
                    }) {
                        Text("Delete", color = MaterialTheme.colorScheme.error)
                    }
                },
                dismissButton = {
                    TextButton(onClick = { dialogMode = DialogMode.Closed }) { Text("Cancel") }
                }
            )
        }
    }

    // ── Main layout ─────────────────────────────────────────────────

    Scaffold(
        modifier = modifier,
        topBar = {
            if (showTopBar) {
                TopAppBar(
                    title = { Text("Planner") },
                    navigationIcon = {
                        TextButton(onClick = onNavigateBack) {
                            Text("Back")
                        }
                    }
                )
            }
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = {
                    dialogMode = when (selectedTab) {
                        0 -> DialogMode.AddTask()
                        1 -> DialogMode.AddNote()
                        else -> DialogMode.Closed
                    }
                },
                containerColor = tabs[selectedTab].accentColor,
                contentColor = Color.White
            ) {
                Icon(Icons.Filled.Add, contentDescription = "Add")
            }
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            if (!showTopBar) {
                Text(
                    text = "Planner",
                    style = MaterialTheme.typography.headlineMedium,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp)
                )
                Spacer(modifier = Modifier.height(4.dp))
            }
            TabRow(
                selectedTabIndex = selectedTab,
                containerColor = MaterialTheme.colorScheme.surface,
                indicator = { tabPositions ->
                    if (selectedTab < tabPositions.size) {
                        TabRowDefaults.Indicator(
                            modifier = Modifier.tabIndicatorOffset(tabPositions[selectedTab]),
                            color = tabs[selectedTab].accentColor,
                            height = 3.dp
                        )
                    }
                }
            ) {
                tabs.forEachIndexed { index, tab ->
                    Tab(
                        selected = selectedTab == index,
                        onClick = { selectedTab = index },
                        text = {
                            Text(
                                tab.title,
                                color = if (selectedTab == index) tab.accentColor
                                else MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    )
                }
            }

            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 12.dp)
            ) {
                when (selectedTab) {
                    0 -> TaskList(
                        tasks = tasks,
                        tab = tabs[0],
                        onEdit = { task ->
                            dialogMode = DialogMode.EditTask(
                                id = task["id"]?.toString().orEmpty(),
                                currentTitle = task["title"]?.toString().orEmpty(),
                                currentDueDate = task["due_date"]?.toString().orEmpty(),
                                currentTriggerPlace = task["trigger_place"]?.toString().orEmpty()
                            )
                        },
                        onDelete = { task ->
                            dialogMode = DialogMode.ConfirmDelete(
                                collection = "tasks",
                                id = task["id"]?.toString().orEmpty(),
                                label = "task"
                            )
                        }
                    )
                    1 -> NoteList(
                        notes = notes,
                        tab = tabs[1],
                        onEdit = { note ->
                            dialogMode = DialogMode.EditNote(
                                id = note["id"]?.toString().orEmpty(),
                                currentContent = note["content"]?.toString().orEmpty()
                            )
                        },
                        onDelete = { note ->
                            dialogMode = DialogMode.ConfirmDelete(
                                collection = "notes",
                                id = note["id"]?.toString().orEmpty(),
                                label = "note"
                            )
                        }
                    )
                }
            }
        }
    }
}

// ── Dialogs ─────────────────────────────────────────────────────────

@Composable
private fun SingleFieldDialog(
    title: String,
    fieldLabel: String,
    initialValue: String,
    singleLine: Boolean = true,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit
) {
    var value by remember(initialValue) { mutableStateOf(initialValue) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(
                value = value,
                onValueChange = { value = it },
                label = { Text(fieldLabel) },
                singleLine = singleLine,
                maxLines = if (singleLine) 1 else 5,
                modifier = Modifier.fillMaxWidth()
            )
        },
        confirmButton = {
            TextButton(
                onClick = { if (value.isNotBlank()) onConfirm(value) },
                enabled = value.isNotBlank()
            ) { Text("Save") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}

@Composable
private fun TaskDialog(
    title: String,
    initialTitle: String,
    initialDueDate: String,
    initialTriggerPlace: String,
    onDismiss: () -> Unit,
    onConfirm: (title: String, dueDate: String, triggerPlace: String) -> Unit
) {
    var taskTitle by remember(initialTitle) { mutableStateOf(initialTitle) }
    var dueDate by remember(initialDueDate) { mutableStateOf(initialDueDate) }
    var triggerPlace by remember(initialTriggerPlace) { mutableStateOf(initialTriggerPlace) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                OutlinedTextField(
                    value = taskTitle,
                    onValueChange = { taskTitle = it },
                    label = { Text("Task Title") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = dueDate,
                    onValueChange = { dueDate = it },
                    label = { Text("Due Date (e.g. 2026-07-20)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = triggerPlace,
                    onValueChange = { triggerPlace = it },
                    label = { Text("Trigger Place (Location)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = { if (taskTitle.isNotBlank()) onConfirm(taskTitle, dueDate, triggerPlace) },
                enabled = taskTitle.isNotBlank()
            ) { Text("Save") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}

// ── Lists ───────────────────────────────────────────────────────────

@Composable
private fun EmptyListMessage(message: String) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = message,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(24.dp)
        )
    }
}

@Composable
private fun TaskList(
    tasks: List<Map<String, Any>>,
    tab: PlannerTab,
    onEdit: (Map<String, Any>) -> Unit,
    onDelete: (Map<String, Any>) -> Unit
) {
    if (tasks.isEmpty()) {
        EmptyListMessage("No tasks yet. Tap + to add one.")
    } else {
        LazyColumn {
            items(tasks, key = { it["id"]?.toString().orEmpty() }) { task ->
                PlannerCard(
                    tab = tab,
                    onClick = { onEdit(task) },
                    onDelete = { onDelete(task) }
                ) {
                    Text(
                        text = task["title"]?.toString().orEmpty(),
                        style = MaterialTheme.typography.bodyLarge
                    )
                    
                    val dueDate = task["due_date"]?.toString().orEmpty()
                    val triggerPlace = task["trigger_place"]?.toString().orEmpty()
                    val triggerCategory = task["trigger_category"]?.toString().orEmpty()

                    if (dueDate.isNotEmpty()) {
                        Text(
                            text = "🕐 Due: $dueDate",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    if (triggerPlace.isNotEmpty()) {
                        val placeLabel = when (triggerPlace.lowercase()) {
                            "home" -> "Home"
                            "outside_home" -> "Outside Home"
                            "work" -> "Work"
                            else -> triggerPlace.replace("_", " ")
                        }
                        Text(
                            text = "📍 Trigger at: $placeLabel",
                            style = MaterialTheme.typography.labelSmall,
                            color = tab.accentColor
                        )
                    }
                    if (triggerCategory.isNotEmpty()) {
                        val catLabel = triggerCategory.replaceFirstChar { if (it.isLowerCase()) it.titlecase(java.util.Locale.ROOT) else it.toString() }
                        Text(
                            text = "🚶 Trigger on activity: $catLabel",
                            style = MaterialTheme.typography.labelSmall,
                            color = tab.accentColor
                        )
                    }

                    task["context_place"]?.let { rawCtx ->
                        val formattedCtx = if (rawCtx is Map<*, *>) {
                            val name = rawCtx["name"]?.toString()
                            if (!name.isNullOrBlank()) name else "Current Location"
                        } else {
                            rawCtx.toString()
                        }
                        Text(
                            text = "Logged near: $formattedCtx",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
                        )
                    }

                }
            }
        }
    }
}

@Composable
private fun NoteList(
    notes: List<Map<String, Any>>,
    tab: PlannerTab,
    onEdit: (Map<String, Any>) -> Unit,
    onDelete: (Map<String, Any>) -> Unit
) {
    if (notes.isEmpty()) {
        EmptyListMessage("No notes yet. Tap + to add one.")
    } else {
        LazyColumn {
            items(notes, key = { it["id"]?.toString().orEmpty() }) { note ->
                PlannerCard(
                    tab = tab,
                    onClick = { onEdit(note) },
                    onDelete = { onDelete(note) }
                ) {
                    Text(
                        text = note["content"]?.toString().orEmpty(),
                        style = MaterialTheme.typography.bodyLarge
                    )
                    note["place"]?.let {
                        Text(
                            text = "Logged near: $it",
                            style = MaterialTheme.typography.labelSmall,
                            color = tab.accentColor
                        )
                    }
                }
            }
        }
    }
}

// ── Shared card ─────────────────────────────────────────────────────

@Composable
private fun PlannerCard(
    tab: PlannerTab,
    onClick: () -> Unit,
    onDelete: () -> Unit,
    content: @Composable () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp)
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(
            modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 16.dp, end = 8.dp),
            verticalAlignment = Alignment.Top
        ) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(tab.accentContainer),
                contentAlignment = Alignment.Center
            ) {
                Icon(tab.icon, contentDescription = null, tint = tab.accentColor, modifier = Modifier.size(20.dp))
            }
            Spacer(Modifier.width(12.dp))
            SelectionContainer(Modifier.weight(1f)) {
                Column {
                    content()
                }
            }
            IconButton(onClick = onDelete) {
                Icon(
                    Icons.Filled.Delete,
                    contentDescription = "Delete",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}
