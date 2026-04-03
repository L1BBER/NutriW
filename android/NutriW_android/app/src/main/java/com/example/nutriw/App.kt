package com.example.nutriw

import androidx.compose.runtime.*
import com.example.nutriw.ui.screens.RootScreen
import com.example.nutriw.ui.theme.NutriWTheme

@Composable
fun NutriWApp() {
    var dark by remember { mutableStateOf(false) }

    NutriWTheme(darkTheme = dark, dynamicColor = true) {
        RootScreen(isDark = dark, onToggleTheme = { dark = !dark })
    }
}
