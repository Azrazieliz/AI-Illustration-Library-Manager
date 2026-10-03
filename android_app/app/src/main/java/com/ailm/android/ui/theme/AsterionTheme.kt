package com.ailm.android.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

object AsterionColors {
    val MatteBlack = Color(0xFF080808)
    val DeepOnyx = Color(0xFF100F0E)
    val Charcoal = Color(0xFF181714)
    val SurfaceMuted = Color(0xFF211F1B)
    val SurfaceElevated = Color(0xFF171512)
    val Gold = Color(0xFFD0B56A)
    val GoldLight = Color(0xFFE8CE83)
    val GoldDark = Color(0xFFA98332)
    val GoldMuted = Color(0xFF665632)
    val Amber = Color(0xFFE1A348)
    val Text = Color(0xFFF5F1E8)
    val TextMuted = Color(0xFFBEB8AC)
    val Divider = Color(0xFF3A352B)
}

val AsterionColorScheme = darkColorScheme(
    primary = AsterionColors.Gold,
    onPrimary = AsterionColors.MatteBlack,
    primaryContainer = AsterionColors.SurfaceMuted,
    onPrimaryContainer = AsterionColors.GoldLight,
    inversePrimary = AsterionColors.GoldDark,
    secondary = AsterionColors.Amber,
    onSecondary = AsterionColors.MatteBlack,
    secondaryContainer = AsterionColors.SurfaceMuted,
    onSecondaryContainer = AsterionColors.Text,
    tertiary = AsterionColors.TextMuted,
    onTertiary = AsterionColors.MatteBlack,
    tertiaryContainer = AsterionColors.SurfaceElevated,
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
    errorContainer = Color(0xFF241A10),
    onErrorContainer = Color(0xFFFFC978),
    outline = AsterionColors.Divider,
    outlineVariant = AsterionColors.SurfaceMuted,
    scrim = Color(0xD9000000),
)

val AsterionTypography = Typography(
    headlineMedium = TextStyle(
        fontSize = 26.sp,
        lineHeight = 31.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 0.15.sp,
    ),
    titleLarge = TextStyle(
        fontSize = 20.sp,
        lineHeight = 25.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 0.10.sp,
    ),
    titleMedium = TextStyle(
        fontSize = 16.sp,
        lineHeight = 21.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 0.05.sp,
    ),
    titleSmall = TextStyle(
        fontSize = 14.sp,
        lineHeight = 19.sp,
        fontWeight = FontWeight.SemiBold,
    ),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 23.sp, fontWeight = FontWeight.Normal),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.Normal),
    bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 17.sp, fontWeight = FontWeight.Normal),
    labelLarge = TextStyle(
        fontSize = 14.sp,
        lineHeight = 19.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 0.15.sp,
    ),
    labelMedium = TextStyle(
        fontSize = 12.sp,
        lineHeight = 16.sp,
        fontWeight = FontWeight.Medium,
        letterSpacing = 0.10.sp,
    ),
)

val AsterionShapes = Shapes(
    extraSmall = RoundedCornerShape(7.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(18.dp),
    extraLarge = RoundedCornerShape(24.dp),
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
