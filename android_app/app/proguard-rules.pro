# Keep bridge entrypoint APIs stable for JNI/Python bridge integration.
-keep class com.ailm.android.bridge.** { *; }

# Keep the ONNX Runtime Java API stable for the native JNI library. The JNI layer
# calls specific constructors and methods such as NodeInfo(String, ValueInfo) and
# expects the Java-side signature to remain compatible with the bundled native
# runtime. R8/shrinking must not rewrite or remove these classes.
-keep class ai.onnxruntime.** {
    *;
}
-keepnames class ai.onnxruntime.**
-dontwarn ai.onnxruntime.**

# Keep Compose tooling metadata minimal.
-keep class androidx.compose.** { *; }
-dontwarn kotlin.**
