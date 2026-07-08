# Keep bridge entrypoint APIs stable for JNI/Python bridge integration.
-keep class com.ailm.android.bridge.** { *; }

# Keep Compose tooling metadata minimal.
-keep class androidx.compose.** { *; }
-dontwarn kotlin.**
