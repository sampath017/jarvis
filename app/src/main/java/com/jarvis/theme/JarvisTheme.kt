package com.jarvis.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

object JarvisColors {
    val primary = Color(0xFF00B4D8)
    val primaryVariant = Color(0xFF0096C7)
    val secondary = Color(0xFF48CAE4)
    val accent = Color(0xFF90E0EF)

    val bgDark = Color(0xFF0A0E14)
    val bgCard = Color(0xFF111822)
    val bgSurface = Color(0xFF161D27)
    val bgElevated = Color(0xFF1A2332)

    val textPrimary = Color(0xFFE0E6ED)
    val textSecondary = Color(0xFF8899AA)
    val textMuted = Color(0xFF4A5568)

    val borderColor = Color(0xFF1E2D3D)
    val divider = Color(0xFF1A2332)

    val success = Color(0xFF00C853)
    val warning = Color(0xFFFFAB00)
    val error = Color(0xFFFF5252)
    val info = Color(0xFF448AFF)

    val arcReactorCore = Color(0xFF00B4D8)
    val arcReactorGlow = Color(0xFF48CAE4)
    val arcReactorOuter = Color(0xFF90E0EF)

    val bgGradientStart = Color(0xFF0A0E14)
    val bgGradientMid = Color(0xFF0D1520)
    val bgGradientEnd = Color(0xFF0A1628)

    val bgGradient = Brush.verticalGradient(
        colors = listOf(bgGradientStart, bgGradientMid, bgGradientEnd)
    )

    val cardGradient = Brush.verticalGradient(
        colors = listOf(
            bgCard.copy(alpha = 0.8f),
            bgSurface.copy(alpha = 0.6f)
        )
    )
}

private val DarkColorScheme = darkColorScheme(
    primary = JarvisColors.primary,
    secondary = JarvisColors.secondary,
    tertiary = JarvisColors.accent,
    background = JarvisColors.bgDark,
    surface = JarvisColors.bgSurface,
    surfaceVariant = JarvisColors.bgCard,
    onPrimary = Color.White,
    onSecondary = Color.White,
    onBackground = JarvisColors.textPrimary,
    onSurface = JarvisColors.textPrimary,
    error = JarvisColors.error,
    onError = Color.White,
    outline = JarvisColors.borderColor,
)

val JarvisTypography = Typography(
    headlineLarge = TextStyle(
        fontWeight = FontWeight.Bold,
        fontSize = 28.sp,
        letterSpacing = 2.sp,
        color = JarvisColors.textPrimary,
    ),
    headlineMedium = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 22.sp,
        letterSpacing = 1.sp,
        color = JarvisColors.textPrimary,
    ),
    headlineSmall = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = 18.sp,
        letterSpacing = 0.5.sp,
        color = JarvisColors.textPrimary,
    ),
    bodyLarge = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        color = JarvisColors.textPrimary,
    ),
    bodyMedium = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        color = JarvisColors.textSecondary,
    ),
    bodySmall = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        color = JarvisColors.textMuted,
    ),
    labelLarge = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        letterSpacing = 1.sp,
        color = JarvisColors.primary,
    ),
    labelMedium = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        letterSpacing = 0.5.sp,
        color = JarvisColors.textSecondary,
    ),
)

@Composable
fun JarvisTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = JarvisTypography,
        content = content
    )
}
