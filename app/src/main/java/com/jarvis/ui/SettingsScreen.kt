package com.jarvis.ui

import android.content.Intent
import android.net.Uri
import android.os.Environment
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.jarvis.theme.JarvisColors
import com.jarvis.viewmodel.JarvisViewModel
import java.io.File

@Composable
fun SettingsScreen(viewModel: JarvisViewModel) {
    val isModelLoaded by viewModel.gemmaEngine.isModelLoaded.collectAsState()
    val loadingProgress by viewModel.gemmaEngine.loadingProgress.collectAsState()
    val context = LocalContext.current

    // File picker for model
    val modelPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri: Uri? ->
        uri?.let {
            // Copy to internal storage or use path
            // For now, try common model location
            val modelPath = "${Environment.getExternalStorageDirectory()}/Download/gemma-2b-it-cpu-int4.bin"
            viewModel.loadModel(modelPath)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(JarvisColors.bgGradient)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // Model section
        SettingsSection(title = "AI MODEL") {
            Surface(
                shape = RoundedCornerShape(12.dp),
                color = JarvisColors.bgCard,
                border = androidx.compose.foundation.BorderStroke(0.5.dp, JarvisColors.borderColor),
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            modifier = Modifier
                                .size(8.dp)
                                .clip(RoundedCornerShape(4.dp))
                                .background(
                                    if (isModelLoaded) JarvisColors.success
                                    else JarvisColors.error
                                ),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = if (isModelLoaded) "Gemma 2B Loaded"
                            else "Model Not Loaded",
                            style = TextStyle(
                                color = JarvisColors.textPrimary,
                                fontSize = 14.sp,
                                fontWeight = FontWeight.Medium,
                            ),
                        )
                    }

                    if (loadingProgress.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = loadingProgress,
                            style = TextStyle(color = JarvisColors.textMuted, fontSize = 12.sp),
                        )
                    }

                    Spacer(modifier = Modifier.height(12.dp))

                    Button(
                        onClick = {
                            // Try default model path first
                            val defaultPath = "${context.filesDir.absolutePath}/gemma-2b-it-cpu-int4.bin"
                            val externalPath = "${Environment.getExternalStorageDirectory()}/Download/gemma-2b-it-cpu-int4.bin"

                            val modelPath = when {
                                File(defaultPath).exists() -> defaultPath
                                File(externalPath).exists() -> externalPath
                                else -> {
                                    // Try workspace path
                                    val workspacePath = "/sdcard/gemma-2b-it-cpu-int4.bin"
                                    if (File(workspacePath).exists()) workspacePath
                                    else externalPath // Will show error
                                }
                            }
                            viewModel.loadModel(modelPath)
                        },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = JarvisColors.primary.copy(alpha = 0.15f),
                            contentColor = JarvisColors.primary,
                        ),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Default.Download, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("Load Model")
                    }

                    if (isModelLoaded) {
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = { viewModel.gemmaEngine.unload() },
                            colors = ButtonDefaults.outlinedButtonColors(
                                contentColor = JarvisColors.error,
                            ),
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("Unload Model")
                        }
                    }
                }
            }
        }

        // Known Places section
        SettingsSection(title = "KNOWN PLACES") {
            val places = viewModel.contextManager.getKnownPlaces()
            if (places.isEmpty()) {
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = JarvisColors.bgCard,
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Icon(
                            Icons.Default.AddLocation,
                            contentDescription = null,
                            tint = JarvisColors.textMuted,
                            modifier = Modifier.size(32.dp),
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            "No places saved yet",
                            style = TextStyle(color = JarvisColors.textMuted, fontSize = 13.sp),
                        )
                        Text(
                            "Label locations like Home, Office, etc.",
                            style = TextStyle(color = JarvisColors.textMuted, fontSize = 11.sp),
                        )
                    }
                }
            } else {
                places.forEach { place ->
                    SettingsItem(
                        icon = Icons.Default.Place,
                        title = place.label,
                        subtitle = "${place.type.name} • ${place.radiusM.toInt()}m radius",
                    )
                }
            }
        }

        // Chat section
        SettingsSection(title = "CHAT") {
            SettingsItem(
                icon = Icons.Default.DeleteSweep,
                title = "Clear Chat History",
                subtitle = "Remove all conversation messages",
                onClick = { viewModel.clearChat() },
            )
        }

        // About section
        SettingsSection(title = "ABOUT") {
            SettingsItem(
                icon = Icons.Default.Info,
                title = "Jarvis v1.0",
                subtitle = "On-device AI assistant powered by Gemma",
            )
            SettingsItem(
                icon = Icons.Default.Shield,
                title = "Privacy-First",
                subtitle = "All processing runs on-device. No data leaves your phone.",
            )
            SettingsItem(
                icon = Icons.Default.Architecture,
                title = "Architecture",
                subtitle = "Native Kotlin • Jetpack Compose • MediaPipe LLM",
            )
        }

        Spacer(modifier = Modifier.height(80.dp))
    }
}

@Composable
private fun SettingsSection(
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column {
        Text(
            text = title,
            style = TextStyle(
                color = JarvisColors.primary,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 2.sp,
            ),
            modifier = Modifier.padding(bottom = 8.dp, start = 4.dp),
        )
        content()
    }
}

@Composable
private fun SettingsItem(
    icon: ImageVector,
    title: String,
    subtitle: String,
    onClick: (() -> Unit)? = null,
) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = JarvisColors.bgCard,
        border = androidx.compose.foundation.BorderStroke(0.5.dp, JarvisColors.borderColor),
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp)
            .then(
                if (onClick != null) Modifier.clickable { onClick() }
                else Modifier
            ),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = JarvisColors.primary.copy(alpha = 0.7f),
                modifier = Modifier.size(20.dp),
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    style = TextStyle(
                        color = JarvisColors.textPrimary,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Medium,
                    ),
                )
                Text(
                    text = subtitle,
                    style = TextStyle(color = JarvisColors.textMuted, fontSize = 12.sp),
                )
            }
            if (onClick != null) {
                Icon(
                    Icons.Default.ChevronRight,
                    contentDescription = null,
                    tint = JarvisColors.textMuted,
                    modifier = Modifier.size(16.dp),
                )
            }
        }
    }
}
