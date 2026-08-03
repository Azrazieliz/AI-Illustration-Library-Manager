package com.ailm.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.graphics.Color
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import com.ailm.android.ui.navigation.AppNavHost

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val appColorScheme = darkColorScheme(
                primary = Color(0xFF0D47A1),
                onPrimary = Color(0xFFFFFFFF),
                primaryContainer = Color(0xFF1565C0),
                onPrimaryContainer = Color(0xFFFFFFFF),
                secondary = Color(0xFF1976D2),
                onSecondary = Color(0xFFFFFFFF),
                background = Color(0xFF081521),
                onBackground = Color(0xFFE3F2FD),
                surface = Color(0xFF0F2233),
                onSurface = Color(0xFFE3F2FD),
                tertiary = Color(0xFF42A5F5),
            )
            MaterialTheme(colorScheme = appColorScheme) {
                Surface {
                    AppNavHost()
                }
            }
        }
    }
}
