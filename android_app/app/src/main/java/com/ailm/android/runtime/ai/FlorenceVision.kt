package com.ailm.android.runtime.ai

internal data class FlorenceImageFeatures(
    val tokens: List<List<Float>>,
    val sequenceLength: Int,
    val hiddenSize: Int,
    val pooled: Boolean = false,
    val normalized: Boolean = false,
)

internal fun decodeFlorenceImageFeatures(values: List<Float>, hiddenSize: Int = 768): FlorenceImageFeatures {
    require(hiddenSize == 768) { "Florence image_features hidden size must be 768" }
    require(values.size % hiddenSize == 0) { "Florence image_features must preserve [B,T,768] values" }
    val tokens = values.chunked(hiddenSize)
    return FlorenceImageFeatures(tokens, tokens.size, hiddenSize)
}

internal fun normalizeFlorencePixel(value: Float, channel: Int): Float {
    val mean = floatArrayOf(0.485f, 0.456f, 0.406f)[channel]
    val std = floatArrayOf(0.229f, 0.224f, 0.225f)[channel]
    return (value / 255f - mean) / std
}
