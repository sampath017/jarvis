package com.jarvis.edge.ui.home

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Chat
import androidx.compose.material.icons.outlined.Checklist
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.jarvis.edge.data.repository.ContextRepository
import com.jarvis.edge.data.repository.FirestoreRepository
import com.jarvis.edge.ui.chat.ChatScreen
import com.jarvis.edge.ui.dashboard.DashboardScreen
import com.jarvis.edge.ui.list.ListScreen
import com.jarvis.edge.ui.theme.FitBlue
import com.jarvis.edge.ui.theme.FitBlueContainer
import com.jarvis.edge.ui.theme.FitGreen
import com.jarvis.edge.ui.theme.FitGreenContainer
import com.jarvis.edge.ui.theme.FitRed
import com.jarvis.edge.ui.theme.FitRedContainer
import com.jarvis.edge.ui.theme.FitYellow
import com.jarvis.edge.ui.theme.FitYellowContainer

private enum class HomeTab(
    val label: String,
    val icon: ImageVector,
    val accentColor: Color,
    val accentContainer: Color
) {
    Today("Today", Icons.Outlined.Home, FitBlue, FitBlueContainer),
    Planner("Planner", Icons.Outlined.Checklist, FitGreen, FitGreenContainer),
    Chat("Chat", Icons.Outlined.Chat, FitYellow, FitYellowContainer),
    Settings("Settings", Icons.Outlined.Settings, FitRed, FitRedContainer)
}

@Composable
fun JarvisHomeScreen(
    uid: String,
    userDisplayName: String?,
    firestoreRepository: FirestoreRepository,
    contextRepository: ContextRepository,
    onSignOut: () -> Unit
) {
    var selectedTabOrdinal by rememberSaveable { mutableIntStateOf(HomeTab.Today.ordinal) }
    val selectedTab = HomeTab.entries[selectedTabOrdinal.coerceIn(HomeTab.entries.indices)]

    Scaffold(
        bottomBar = {
            NavigationBar(
                containerColor = MaterialTheme.colorScheme.surface,
                tonalElevation = 0.dp
            ) {
                HomeTab.entries.forEach { tab ->
                    val selected = selectedTab == tab
                    NavigationBarItem(
                        selected = selected,
                        onClick = { selectedTabOrdinal = tab.ordinal },
                        icon = {
                            Icon(
                                tab.icon,
                                contentDescription = tab.label,
                                tint = if (selected) MaterialTheme.colorScheme.onSurface
                                       else MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        },
                        label = {
                            Text(
                                tab.label,
                                color = if (selected) MaterialTheme.colorScheme.onSurface
                                        else MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = MaterialTheme.colorScheme.onSurface,
                            selectedTextColor = MaterialTheme.colorScheme.onSurface,
                            unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                            unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                            indicatorColor = Color.Transparent
                        )
                    )
                }
            }
        }
    ) { innerPadding ->
        when (selectedTab) {
            HomeTab.Today -> DashboardScreen(
                uid = uid,
                userDisplayName = userDisplayName,
                firestoreRepository = firestoreRepository,
                modifier = Modifier.padding(innerPadding)
            )

            HomeTab.Planner -> ListScreen(
                uid = uid,
                firestoreRepository = firestoreRepository,
                showTopBar = false,
                modifier = Modifier.padding(innerPadding)
            )

            HomeTab.Chat -> ChatScreen(
                uid = uid,
                firestoreRepository = firestoreRepository,
                contextRepository = contextRepository,
                modifier = Modifier.padding(innerPadding)
            )

            HomeTab.Settings -> SettingsScreen(
                uid = uid,
                firestoreRepository = firestoreRepository,
                userDisplayName = userDisplayName,
                onSignOut = onSignOut,
                modifier = Modifier.padding(innerPadding)
            )
        }
    }
}

@Composable
private fun SettingsScreen(
    uid: String,
    firestoreRepository: FirestoreRepository,
    userDisplayName: String?,
    onSignOut: () -> Unit,
    modifier: Modifier = Modifier
) {
    val scope = rememberCoroutineScope()
    var isDeleting by remember { mutableStateOf(false) }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Text("Settings", style = MaterialTheme.typography.headlineMedium)
            Text(
                userDisplayName?.let { "Signed in as $it" } ?: "Personalize your Jarvis experience",
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        item {
            SettingsCard(
                icon = Icons.Outlined.Lock,
                iconColor = FitGreen,
                iconContainer = FitGreenContainer
            ) {
                Text("Privacy", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                Text(
                    "Location is used only to add context to verified rides. Activity Recognition is always active.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        item {
            Button(
                onClick = {
                    isDeleting = true
                    scope.launch {
                        firestoreRepository.deleteAllChatThreads(uid)
                        isDeleting = false
                    }
                },
                enabled = !isDeleting,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.error,
                    contentColor = MaterialTheme.colorScheme.onError
                )
            ) {
                Text(if (isDeleting) "Deleting chats..." else "Delete all chats from backend")
            }
        }

        item {
            Button(
                onClick = onSignOut,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp)
            ) {
                Text("Sign out")
            }
        }
    }
}

@Composable
private fun SettingsCard(
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    iconColor: Color = FitBlue,
    iconContainer: Color = FitBlueContainer,
    content: @Composable () -> Unit
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.Top
        ) {
            if (icon != null) {
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(iconContainer),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(icon, contentDescription = null, tint = iconColor)
                }
                Spacer(Modifier.width(14.dp))
            }
            Column(Modifier.weight(1f), content = { content() })
        }
    }
}
