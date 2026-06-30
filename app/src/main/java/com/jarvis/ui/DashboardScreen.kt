package com.jarvis.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.jarvis.models.VehicleSessionState
import com.jarvis.theme.JarvisColors
import com.jarvis.viewmodel.JarvisViewModel

@Composable
fun DashboardScreen(viewModel: JarvisViewModel) {
    val context by viewModel.jarvisContext.collectAsState()
    val isClassifying by viewModel.motionClassifier.isClassifying.collectAsState()
    val classificationResult by viewModel.motionClassifier.classificationResult.collectAsState()
    val isTracking by viewModel.contextManager.isTracking.collectAsState()
    val vehicleSession by viewModel.vehicleSessionManager.currentSession.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(JarvisColors.bgGradient)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // Status header
        StatusCard(
            isTracking = isTracking,
            onToggleTracking = {
                if (isTracking) viewModel.stopLocationTracking()
                else viewModel.startLocationTracking()
            },
        )

        // Location card
        DashboardCard(
            title = "LOCATION",
            icon = Icons.Default.LocationOn,
        ) {
            val loc = context.location
            if (loc != null) {
                InfoRow("Latitude", "%.6f".format(loc.latitude))
                InfoRow("Longitude", "%.6f".format(loc.longitude))
                InfoRow("Accuracy", "%.1fm".format(loc.accuracy))
                InfoRow("Speed", "%.1f km/h".format(loc.speed * 3.6f))
                InfoRow("Altitude", "%.1fm".format(loc.altitude))
            } else {
                Text(
                    "Location not available",
                    style = TextStyle(color = JarvisColors.textMuted, fontSize = 13.sp),
                )
            }
        }

        // Place context card
        DashboardCard(
            title = "PLACE CONTEXT",
            icon = Icons.Default.Place,
        ) {
            val place = context.placeContext
            if (place != null) {
                InfoRow("Label", place.label)
                InfoRow("Type", place.placeType.name)
                InfoRow("Confidence", "%.0f%%".format(place.confidence * 100))
                if (place.evidence.isNotEmpty()) {
                    InfoRow("Evidence", place.evidence.joinToString(", "))
                }
            } else {
                Text(
                    "No place context resolved",
                    style = TextStyle(color = JarvisColors.textMuted, fontSize = 13.sp),
                )
            }
        }

        // Vehicle session card
        DashboardCard(
            title = "VEHICLE SESSION",
            icon = Icons.Default.DirectionsBike,
        ) {
            if (vehicleSession != null) {
                val session = vehicleSession!!
                InfoRow("Vehicle", session.vehicleIdentity)
                InfoRow("State", session.state.name)
                InfoRow("Confidence", "%.0f%%".format(session.confidence * 100))

                // State indicator
                val stateColor = when (session.state) {
                    VehicleSessionState.ACTIVE_RIDING -> JarvisColors.success
                    VehicleSessionState.PARKED_CANDIDATE, VehicleSessionState.PARKED_NEARBY -> JarvisColors.warning
                    VehicleSessionState.CLASSIFYING_VEHICLE, VehicleSessionState.RESUME_CHECK -> JarvisColors.info
                    else -> JarvisColors.textMuted
                }
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(top = 8.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .clip(CircleShape)
                            .background(stateColor)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = when (session.state) {
                            VehicleSessionState.ACTIVE_RIDING -> "Actively riding"
                            VehicleSessionState.PARKED_CANDIDATE -> "Vehicle possibly parked"
                            VehicleSessionState.PARKED_NEARBY -> "Parked nearby"
                            VehicleSessionState.CLASSIFYING_VEHICLE -> "Classifying vehicle..."
                            VehicleSessionState.RESUME_CHECK -> "Checking resume..."
                            else -> session.state.name
                        },
                        style = TextStyle(color = stateColor, fontSize = 13.sp, fontWeight = FontWeight.Medium),
                    )
                }
            } else {
                Text(
                    "No active vehicle session",
                    style = TextStyle(color = JarvisColors.textMuted, fontSize = 13.sp),
                )
            }

            Spacer(modifier = Modifier.height(12.dp))

            // Classify button
            Button(
                onClick = { viewModel.classifyVehicle() },
                enabled = !isClassifying,
                colors = ButtonDefaults.buttonColors(
                    containerColor = JarvisColors.primary.copy(alpha = 0.15f),
                    contentColor = JarvisColors.primary,
                ),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (isClassifying) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = JarvisColors.primary,
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Classifying (10s burst)...")
                } else {
                    Icon(Icons.Default.Sensors, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Run IMU Classification Burst")
                }
            }

            // Last classification result
            classificationResult?.let { result ->
                Spacer(modifier = Modifier.height(8.dp))
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = JarvisColors.bgDark.copy(alpha = 0.5f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(
                            "Last Classification",
                            style = TextStyle(
                                color = JarvisColors.textMuted,
                                fontSize = 10.sp,
                                letterSpacing = 1.sp,
                            ),
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        InfoRow("Identity", result.vehicleIdentity)
                        InfoRow("Confidence", "%.0f%%".format(result.confidence * 100))
                        InfoRow("Type", result.motionType)
                        InfoRow("Samples", "${result.sampleCount}")
                    }
                }
            }
        }

        // Motion state card
        DashboardCard(
            title = "MOTION STATE",
            icon = Icons.Default.DirectionsWalk,
        ) {
            InfoRow("State", context.motion.name)
        }

        Spacer(modifier = Modifier.height(80.dp))
    }
}

@Composable
private fun StatusCard(
    isTracking: Boolean,
    onToggleTracking: () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = JarvisColors.bgCard,
        border = androidx.compose.foundation.BorderStroke(0.5.dp, JarvisColors.borderColor),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ArcReactorIndicator(
                size = 48.dp,
                isActive = isTracking,
                isProcessing = false,
            )
            Spacer(modifier = Modifier.width(16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = if (isTracking) "SYSTEMS ACTIVE" else "SYSTEMS OFFLINE",
                    style = TextStyle(
                        color = if (isTracking) JarvisColors.success else JarvisColors.textMuted,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 2.sp,
                    ),
                )
                Text(
                    text = if (isTracking) "Location and context tracking enabled"
                    else "Tap to enable context tracking",
                    style = TextStyle(color = JarvisColors.textSecondary, fontSize = 12.sp),
                )
            }
            Switch(
                checked = isTracking,
                onCheckedChange = { onToggleTracking() },
                colors = SwitchDefaults.colors(
                    checkedThumbColor = JarvisColors.primary,
                    checkedTrackColor = JarvisColors.primary.copy(alpha = 0.3f),
                    uncheckedThumbColor = JarvisColors.textMuted,
                    uncheckedTrackColor = JarvisColors.bgDark,
                ),
            )
        }
    }
}

@Composable
private fun DashboardCard(
    title: String,
    icon: ImageVector,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = JarvisColors.bgCard,
        border = androidx.compose.foundation.BorderStroke(0.5.dp, JarvisColors.borderColor),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = JarvisColors.primary,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = title,
                    style = TextStyle(
                        color = JarvisColors.primary,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                        letterSpacing = 2.sp,
                    ),
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
            content()
        }
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = TextStyle(color = JarvisColors.textMuted, fontSize = 12.sp),
        )
        Text(
            text = value,
            style = TextStyle(color = JarvisColors.textPrimary, fontSize = 12.sp, fontWeight = FontWeight.Medium),
        )
    }
}
