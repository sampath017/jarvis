package com.jarvis.edge.ui.dashboard

import androidx.compose.foundation.Canvas
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.jarvis.edge.data.repository.FirestoreRepository
import com.jarvis.edge.ui.theme.FitBlue
import com.jarvis.edge.ui.theme.FitGreen
import com.jarvis.edge.ui.theme.FitRed
import com.jarvis.edge.ui.theme.FitYellow
import kotlinx.coroutines.launch

@Composable
fun DashboardScreen(
    uid: String,
    userDisplayName: String?,
    firestoreRepository: FirestoreRepository,
    modifier: Modifier = Modifier
) {
    val activeSession by firestoreRepository.getActiveSession(uid).collectAsState(initial = null)
    val vehicle = activeSession?.get("vehicle_class")?.toString() ?: "No verified ride"
    val progress = if (activeSession == null) 0.0f else 0.68f
    val scope = rememberCoroutineScope()
    var isEndingSession by remember { mutableStateOf(false) }
    var sessionError by remember { mutableStateOf<String?>(null) }

    SelectionContainer {
        LazyColumn(
            modifier = modifier.fillMaxSize(),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp)
        ) {
        item {
            Text(
                text = greetingFor(userDisplayName),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = "Your assistant for movement, planning, and chat.",
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                shape = RoundedCornerShape(24.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(20.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    ActivityRing(progress = progress, isActive = activeSession != null)
                    Spacer(Modifier.width(20.dp))
                    Column(Modifier.weight(1f)) {
                        Text("Today", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.height(4.dp))
                        Text(
                            text = if (activeSession == null) "Ready when you are" else "Ride in progress",
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.SemiBold
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            text = if (activeSession == null) {
                                "Jarvis will verify travel when Activity Recognition detects movement."
                            } else {
                                "$vehicle is verified and being tracked."
                            },
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        if (activeSession != null) {
                            Spacer(Modifier.height(8.dp))
                            TextButton(
                                onClick = {
                                    val sessionId = activeSession?.get("id")?.toString() ?: return@TextButton
                                    isEndingSession = true
                                    sessionError = null
                                    scope.launch {
                                        val result = firestoreRepository.completeSession(uid, sessionId)
                                        isEndingSession = false
                                        sessionError = result.exceptionOrNull()?.message
                                    }
                                },
                                enabled = !isEndingSession
                            ) {
                                Text(if (isEndingSession) "Ending…" else "End ride")
                            }
                            sessionError?.let { error ->
                                Text(error, color = MaterialTheme.colorScheme.error)
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
private fun ActivityRing(progress: Float, isActive: Boolean) {
    val ringColors = listOf(FitRed, FitYellow, FitGreen, FitBlue)
    Box(contentAlignment = Alignment.Center, modifier = Modifier.size(96.dp)) {
        Canvas(Modifier.fillMaxSize()) {
            val stroke = 8.dp.toPx()
            val gap = 4f
            val segmentSweep = (360f - gap * ringColors.size) / ringColors.size
            ringColors.forEachIndexed { index, color ->
                val startAngle = -90f + index * (segmentSweep + gap)
                val sweep = if (isActive) segmentSweep * (0.4f + progress * 0.6f) else segmentSweep * 0.25f
                drawArc(
                    color = color.copy(alpha = 0.2f),
                    startAngle = startAngle,
                    sweepAngle = segmentSweep,
                    useCenter = false,
                    style = Stroke(width = stroke, cap = StrokeCap.Round)
                )
                drawArc(
                    color = color,
                    startAngle = startAngle,
                    sweepAngle = sweep,
                    useCenter = false,
                    style = Stroke(width = stroke, cap = StrokeCap.Round)
                )
            }
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = if (isActive) "Live" else "Idle",
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.Bold
            )
        }
    }
}

private fun greetingFor(displayName: String?): String {
    val firstName = displayName?.trim()?.split(" ")?.firstOrNull().orEmpty()
    return if (firstName.isBlank()) "Good day" else "Good day, $firstName"
}
