package com.jarvis.edge.ui.theme

import android.app.Activity
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

private val DarkColorScheme = darkColorScheme(
    primary = FitBlue,
    onPrimary = Color.White,
    primaryContainer = FitBlueContainer,
    onPrimaryContainer = FitBlue,
    secondary = FitGreen,
    onSecondary = Color.White,
    secondaryContainer = FitGreenContainer,
    onSecondaryContainer = FitGreen,
    tertiary = FitRed,
    onTertiary = Color.White,
    tertiaryContainer = FitRedContainer,
    onTertiaryContainer = FitRed,
    background = FitBackground,
    onBackground = FitOnSurface,
    surface = FitSurface,
    onSurface = FitOnSurface,
    surfaceVariant = FitSurfaceVariant,
    onSurfaceVariant = FitOnSurfaceVariant,
    error = FitRed,
    onError = Color.White
)

@Composable
fun JarvisTheme(content: @Composable () -> Unit) {
    val colorScheme = DarkColorScheme
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = colorScheme.background.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = false
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}
