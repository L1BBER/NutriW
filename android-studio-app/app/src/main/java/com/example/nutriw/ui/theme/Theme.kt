package com.example.nutriw.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

private val DarkColorScheme = darkColorScheme(
    primary = GlacierBlue,
    onPrimary = DeepOcean,
    secondary = BrightMint,
    onSecondary = DeepOcean,
    tertiary = SignalAmber,
    background = NightBlue,
    onBackground = IceText,
    surface = NightSurface,
    onSurface = IceText,
    surfaceVariant = NightSurfaceHigh,
    onSurfaceVariant = SoftIceText,
    outline = NightLine,
    error = AlertRose
)

private val LightColorScheme = lightColorScheme(
    primary = HarborBlue,
    onPrimary = FrostWhite,
    secondary = AquaMint,
    onSecondary = FrostWhite,
    tertiary = AlertRose,
    background = FrostWhite,
    onBackground = DeepOcean,
    surface = Color.White,
    onSurface = DeepOcean,
    surfaceVariant = MistBlue,
    onSurfaceVariant = SlateBlue,
    outline = CloudBlue,
    error = AlertRose
)

@Composable
fun NutriWTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    // Dynamic color is available on Android 12+
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColorScheme
        else -> LightColorScheme
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}
