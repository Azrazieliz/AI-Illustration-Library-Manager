package com.ailm.android.runtime.ai

internal object LlamaCppNative {
    @Volatile private var loaded = false

    fun load(): Boolean = synchronized(this) {
        if (loaded) return true
        return runCatching {
            System.loadLibrary("qwen_runtime")
            loaded = true
        }.isSuccess
    }

    external fun nativeProbe(): String
    external fun nativeLoad(path: String, contextSize: Int, threads: Int): Long
    external fun nativeLoadMultimodal(path: String, mmprojPath: String, contextSize: Int, threads: Int): Long
    external fun nativeGenerate(handle: Long, userPrompt: String, maxNewTokens: Int): String
    external fun nativeGenerateMultimodal(handle: Long, userPrompt: String, rgb: ByteArray, width: Int, height: Int, maxNewTokens: Int): String
    external fun nativeCancel(handle: Long)
    external fun nativeRelease(handle: Long)
}

internal interface LlamaCppRuntimeBridge {
    fun probe(): String
    fun loadModel(path: String, contextSize: Int, threads: Int): Long
    fun loadMultimodalModel(path: String, mmprojPath: String, contextSize: Int, threads: Int): Long
    fun generate(handle: Long, prompt: String, maxNewTokens: Int): String
    fun generateMultimodal(handle: Long, prompt: String, rgb: ByteArray, width: Int, height: Int, maxNewTokens: Int): String
    fun cancel(handle: Long)
    fun release(handle: Long)
}

internal object RealLlamaCppRuntimeBridge : LlamaCppRuntimeBridge {
    override fun probe(): String {
        check(LlamaCppNative.load()) { "native_backend_unavailable" }
        return LlamaCppNative.nativeProbe()
    }

    override fun loadModel(path: String, contextSize: Int, threads: Int): Long {
        check(LlamaCppNative.load()) { "native_backend_unavailable" }
        return LlamaCppNative.nativeLoad(path, contextSize, threads)
    }

    override fun loadMultimodalModel(path: String, mmprojPath: String, contextSize: Int, threads: Int): Long {
        check(LlamaCppNative.load()) { "native_backend_unavailable" }
        return LlamaCppNative.nativeLoadMultimodal(path, mmprojPath, contextSize, threads)
    }

    override fun generate(handle: Long, prompt: String, maxNewTokens: Int): String = LlamaCppNative.nativeGenerate(handle, prompt, maxNewTokens)
    override fun generateMultimodal(handle: Long, prompt: String, rgb: ByteArray, width: Int, height: Int, maxNewTokens: Int): String =
        LlamaCppNative.nativeGenerateMultimodal(handle, prompt, rgb, width, height, maxNewTokens)
    override fun cancel(handle: Long) = LlamaCppNative.nativeCancel(handle)
    override fun release(handle: Long) = LlamaCppNative.nativeRelease(handle)
}