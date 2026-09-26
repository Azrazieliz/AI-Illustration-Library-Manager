package com.ailm.android.runtime.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NsfwOnnxContractTest {
    @Test
    fun `stable softmax decoder maps deterministic logits to expected top class`() {
        val values = listOf(1.0f, 1.0f, 0.0f, 0.0f, 0.0f)
        val contract = ModelInferenceContract(
            taskType = "nsfw_classification",
            tokenizer = TokenizerContract(
                type = "none",
                vocabulary = emptyList(),
                unknownToken = "[UNK]",
                startToken = "[CLS]",
                endToken = "[SEP]",
                padToken = "[PAD]",
                maxLength = 0,
            ),
            imagePreprocessing = ImagePreprocessingContract(
                enabled = true,
                width = 224,
                height = 224,
                channels = 3,
                colorSpace = "rgb",
                resizeMode = "stretch",
                scale = 1f / 255f,
                mean = listOf(0.5f, 0.5f, 0.5f),
                standardDeviation = listOf(0.5f, 0.5f, 0.5f),
            ),
            inputs = listOf(
                TensorInputContract(
                    name = "pixel_values",
                    source = "image",
                    dataType = "float32",
                    layout = "nchw",
                    shape = listOf(1, 3, 224, 224),
                    payloadKey = "",
                    quantizationScale = 0f,
                    quantizationZeroPoint = 0,
                ),
            ),
            outputs = listOf(
                TensorOutputContract(
                    name = "logits",
                    index = 0,
                    dataType = "float32",
                    quantizationScale = 0f,
                    quantizationZeroPoint = 0,
                ),
            ),
            outputDecoder = OutputDecoderContract(
                type = "classification",
                outputName = "logits",
                labels = listOf("drawings", "hentai", "neutral", "porn", "sexy"),
                scoreOutputName = "",
                labelOutputName = "",
                boxOutputName = "",
                maxResults = 5,
                endTokenId = null,
            ),
            confidence = ConfidenceContract(type = "softmax", threshold = 0f),
        )

        val logits = listOf(1.0f, 1.0f, 0.0f, 0.0f, 0.0f)
        val scores = RuntimeOutputMapper.stableSoftmax(logits)
        val topIndex = scores.withIndex().maxByOrNull { it.value }?.index ?: -1
        assertEquals(0, topIndex)
        assertEquals(0, topIndex)
        assertTrue(scores.size == 5)
    }
}
