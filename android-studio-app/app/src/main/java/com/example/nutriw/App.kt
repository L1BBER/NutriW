package com.example.nutriw

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.example.nutriw.ui.screens.RootScreen
import com.example.nutriw.ui.theme.NutriWTheme

@Composable
fun NutriWApp() {
    var dark by rememberSaveable { mutableStateOf(false) }

    NutriWTheme(darkTheme = dark, dynamicColor = false) {
        RootScreen(isDark = dark, onToggleTheme = { dark = !dark })
    }
}
