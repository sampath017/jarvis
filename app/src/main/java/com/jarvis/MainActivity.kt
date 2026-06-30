package com.jarvis

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jarvis.theme.JarvisColors
import com.jarvis.theme.JarvisTheme
import com.jarvis.ui.*
import com.jarvis.viewmodel.JarvisViewModel
import java.text.SimpleDateFormat
import java.util.*

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Request permissions
        val permissionLauncher = registerForActivityResult(
            ActivityResultContracts.RequestMultiplePermissions()
        ) { _ -> }

        permissionLauncher.launch(
            arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION,
            )
        )

        setContent {
            JarvisTheme {
                val viewModel: JarvisViewModel = viewModel()
                val isInitialized by viewModel.isInitialized.collectAsState()

                if (isInitialized) {
                    JarvisHome(viewModel)
                } else {
                    SplashScreen()
                }
            }
        }
    }
}

@Composable
private fun JarvisHome(viewModel: JarvisViewModel) {
    val currentTab by viewModel.currentTab.collectAsState()
    val titles = listOf("JARVIS", "DASHBOARD", "SETTINGS")

    Scaffold(
        containerColor = JarvisColors.bgDark,
        topBar = {
            JarvisTopBar(title = titles[currentTab])
        },
        bottomBar = {
            JarvisBottomNav(
                currentTab = currentTab,
                onTabSelected = { viewModel.setCurrentTab(it) },
            )
        },
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(JarvisColors.bgGradient),
        ) {
            when (currentTab) {
                0 -> ChatScreen(viewModel)
                1 -> DashboardScreen(viewModel)
                2 -> SettingsScreen(viewModel)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun JarvisTopBar(title: String) {
    val timeFormat = SimpleDateFormat("HH:mm", Locale.getDefault())
    val currentTime = remember { mutableStateOf(timeFormat.format(Date())) }

    // Update time every minute
    LaunchedEffect(Unit) {
        while (true) {
            currentTime.value = timeFormat.format(Date())
            kotlinx.coroutines.delay(30_000L)
        }
    }

    Surface(
        color = JarvisColors.bgDark.copy(alpha = 0.95f),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Arc reactor mini icon
            Box(
                modifier = Modifier
                    .size(28.dp),
                contentAlignment = Alignment.Center,
            ) {
                ArcReactorIndicator(
                    size = 28.dp,
                    isActive = true,
                    isProcessing = false,
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            Text(
                text = title,
                style = TextStyle(
                    color = JarvisColors.textPrimary,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    letterSpacing = 3.sp,
                ),
            )
            Spacer(modifier = Modifier.weight(1f))
            Text(
                text = currentTime.value,
                style = TextStyle(
                    color = JarvisColors.primary.copy(alpha = 0.7f),
                    fontSize = 14.sp,
                    letterSpacing = 1.sp,
                ),
            )
        }
    }
}

@Composable
private fun JarvisBottomNav(
    currentTab: Int,
    onTabSelected: (Int) -> Unit,
) {
    Surface(
        color = JarvisColors.bgDark.copy(alpha = 0.95f),
        border = androidx.compose.foundation.BorderStroke(
            0.5.dp, JarvisColors.borderColor.copy(alpha = 0.5f)
        ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(vertical = 8.dp),
            horizontalArrangement = Arrangement.SpaceAround,
        ) {
            NavItem(
                index = 0,
                icon = Icons.Outlined.ChatBubbleOutline,
                selectedIcon = Icons.Filled.ChatBubble,
                label = "Chat",
                isSelected = currentTab == 0,
                onClick = { onTabSelected(0) },
            )
            NavItem(
                index = 1,
                icon = Icons.Outlined.Dashboard,
                selectedIcon = Icons.Filled.Dashboard,
                label = "Dashboard",
                isSelected = currentTab == 1,
                onClick = { onTabSelected(1) },
            )
            NavItem(
                index = 2,
                icon = Icons.Outlined.Settings,
                selectedIcon = Icons.Filled.Settings,
                label = "Settings",
                isSelected = currentTab == 2,
                onClick = { onTabSelected(2) },
            )
        }
    }
}

@Composable
private fun NavItem(
    index: Int,
    icon: ImageVector,
    selectedIcon: ImageVector,
    label: String,
    isSelected: Boolean,
    onClick: () -> Unit,
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .clickable(onClick = onClick)
            .padding(horizontal = 20.dp, vertical = 4.dp),
    ) {
        Icon(
            imageVector = if (isSelected) selectedIcon else icon,
            contentDescription = label,
            tint = if (isSelected) JarvisColors.primary else JarvisColors.textMuted,
            modifier = Modifier.size(22.dp),
        )
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = label,
            style = TextStyle(
                color = if (isSelected) JarvisColors.primary else JarvisColors.textMuted,
                fontSize = 10.sp,
                fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal,
            ),
        )
        if (isSelected) {
            Spacer(modifier = Modifier.height(4.dp))
            Box(
                modifier = Modifier
                    .width(16.dp)
                    .height(2.dp)
                    .clip(RoundedCornerShape(1.dp))
                    .background(JarvisColors.primary),
            )
        }
    }
}

@Composable
private fun SplashScreen() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(JarvisColors.bgGradient),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            ArcReactorIndicator(
                size = 100.dp,
                isActive = true,
                isProcessing = true,
            )
            Spacer(modifier = Modifier.height(32.dp))
            Text(
                text = "JARVIS",
                style = TextStyle(
                    color = JarvisColors.primary,
                    fontSize = 32.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 8.sp,
                ),
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "Initializing Systems...",
                style = TextStyle(
                    color = JarvisColors.textSecondary,
                    fontSize = 14.sp,
                ),
            )
        }
    }
}
