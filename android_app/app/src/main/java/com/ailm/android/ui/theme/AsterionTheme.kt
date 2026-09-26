package com.ailm.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.unit.dp

object AsterionColors {
    val MatteBlack = Color(0xFF080808)
    val DeepOnyx = Color(0xFF141414)
    val Charcoal = Color(0xFF1A1A1A)
    val SurfaceMuted = Color(0xFF292929)
    val Gold = Color(0xFFC8A95A)
    val GoldLight = Color(0xFFE0C16F)
    val GoldDark = Color(0xFFA67C1A)
    val Amber = Color(0xFFE0A23D)
    val Text = Color(0xFFF3F0E8)
    val TextMuted = Color(0xFFCBC5B8)
    val Divider = Color(0xFF383838)
}

val AsterionColorScheme = darkColorScheme(
    primary = AsterionColors.Gold,
    onPrimary = AsterionColors.MatteBlack,
    primaryContainer = AsterionColors.DeepOnyx,
    onPrimaryContainer = AsterionColors.GoldLight,
    inversePrimary = AsterionColors.GoldDark,
    secondary = AsterionColors.Amber,
    onSecondary = AsterionColors.MatteBlack,
    secondaryContainer = AsterionColors.SurfaceMuted,
    onSecondaryContainer = AsterionColors.Text,
    tertiary = AsterionColors.TextMuted,
    onTertiary = AsterionColors.MatteBlack,
    tertiaryContainer = AsterionColors.SurfaceMuted,
    onTertiaryContainer = AsterionColors.Text,
    background = AsterionColors.MatteBlack,
    onBackground = AsterionColors.Text,
    surface = AsterionColors.DeepOnyx,
    onSurface = AsterionColors.Text,
    surfaceVariant = AsterionColors.Charcoal,
    onSurfaceVariant = AsterionColors.TextMuted,
    surfaceTint = AsterionColors.Gold,
    inverseSurface = AsterionColors.Text,
    inverseOnSurface = AsterionColors.MatteBlack,
    error = AsterionColors.Amber,
    onError = AsterionColors.MatteBlack,
    errorContainer = AsterionColors.DeepOnyx,
    onErrorContainer = AsterionColors.Amber,
    outline = AsterionColors.Divider,
    outlineVariant = AsterionColors.SurfaceMuted,
    scrim = Color(0xCC000000),
)

val AsterionTypography = Typography(
    headlineMedium = TextStyle(fontSize = 24.sp, lineHeight = 30.sp, fontWeight = FontWeight.SemiBold),
    titleLarge = TextStyle(fontSize = 20.sp, lineHeight = 26.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 16.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold),
    titleSmall = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.SemiBold),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 23.sp, fontWeight = FontWeight.Normal),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.Normal),
    bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 17.sp, fontWeight = FontWeight.Normal),
    labelLarge = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.SemiBold),
    labelMedium = TextStyle(fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium),
)

val AsterionShapes = Shapes(
    extraSmall = RoundedCornerShape(4.dp),
    small = RoundedCornerShape(6.dp),
    medium = RoundedCornerShape(8.dp),
    large = RoundedCornerShape(10.dp),
    extraLarge = RoundedCornerShape(12.dp),
)

@Composable
fun AsterionTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = AsterionColorScheme,
        typography = AsterionTypography,
        shapes = AsterionShapes,
        content = content,
    )
}