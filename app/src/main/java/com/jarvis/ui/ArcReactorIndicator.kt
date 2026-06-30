package com.jarvis.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.jarvis.theme.JarvisColors
import kotlin.math.cos
import kotlin.math.sin

/**
 * Arc Reactor indicator widget – the iconic Jarvis visual element.
 * Animated glowing concentric rings with a pulsing core.
 */
@Composable
fun ArcReactorIndicator(
    modifier: Modifier = Modifier,
    size: Dp = 80.dp,
    isActive: Boolean = true,
    isProcessing: Boolean = false,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "arc_reactor")

    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = 0.4f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1200, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse",
    )

    val rotationAngle by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = if (isProcessing) 1500 else 4000,
                easing = LinearEasing,
            ),
        ),
        label = "rotation",
    )

    val glowRadius by infiniteTransition.animateFloat(
        initialValue = 0.6f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(2000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "glow",
    )

    val activeAlpha = if (isActive) 1f else 0.3f

    Canvas(modifier = modifier.size(size)) {
        val center = Offset(this.size.width / 2, this.size.height / 2)
        val maxRadius = this.size.minDimension / 2

        // Outer glow
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(
                    JarvisColors.arcReactorGlow.copy(alpha = 0.15f * activeAlpha * glowRadius),
                    JarvisColors.arcReactorGlow.copy(alpha = 0f),
                ),
                center = center,
                radius = maxRadius * 1.3f,
            ),
            radius = maxRadius * 1.3f,
            center = center,
        )

        // Outer ring
        drawCircle(
            color = JarvisColors.arcReactorOuter.copy(alpha = 0.3f * activeAlpha),
            radius = maxRadius * 0.95f,
            center = center,
            style = Stroke(width = 1.5f),
        )

        // Middle ring (rotating segments)
        rotate(rotationAngle, pivot = center) {
            drawArcSegments(center, maxRadius * 0.78f, activeAlpha)
        }

        // Inner ring
        drawCircle(
            color = JarvisColors.primary.copy(alpha = 0.5f * activeAlpha),
            radius = maxRadius * 0.55f,
            center = center,
            style = Stroke(width = 2f),
        )

        // Core glow
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(
                    JarvisColors.arcReactorCore.copy(alpha = pulseAlpha * activeAlpha),
                    JarvisColors.arcReactorGlow.copy(alpha = 0.3f * activeAlpha),
                    JarvisColors.arcReactorCore.copy(alpha = 0f),
                ),
                center = center,
                radius = maxRadius * 0.4f,
            ),
            radius = maxRadius * 0.4f,
            center = center,
        )

        // Core dot
        drawCircle(
            color = JarvisColors.arcReactorCore.copy(alpha = activeAlpha),
            radius = maxRadius * 0.12f,
            center = center,
        )
    }
}

private fun DrawScope.drawArcSegments(center: Offset, radius: Float, alpha: Float) {
    val segmentCount = 8
    val gapAngle = 8.0
    val segmentAngle = (360.0 / segmentCount) - gapAngle

    for (i in 0 until segmentCount) {
        val startAngle = i * (segmentAngle + gapAngle)
        val startRad = Math.toRadians(startAngle)
        val endRad = Math.toRadians(startAngle + segmentAngle)

        val startX = center.x + radius * cos(startRad).toFloat()
        val startY = center.y + radius * sin(startRad).toFloat()
        val endX = center.x + radius * cos(endRad).toFloat()
        val endY = center.y + radius * sin(endRad).toFloat()

        drawArc(
            color = JarvisColors.primary.copy(alpha = 0.7f * alpha),
            startAngle = startAngle.toFloat(),
            sweepAngle = segmentAngle.toFloat(),
            useCenter = false,
            style = Stroke(width = 2.5f, cap = StrokeCap.Round),
            topLeft = Offset(center.x - radius, center.y - radius),
            size = androidx.compose.ui.geometry.Size(radius * 2, radius * 2),
        )
    }
}
