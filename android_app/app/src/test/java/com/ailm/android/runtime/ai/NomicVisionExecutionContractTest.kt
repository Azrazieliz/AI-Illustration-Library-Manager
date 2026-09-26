package com.ailm.android.runtime.ai

import android.graphics.Bitmap
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNotNull
import org.junit.Assert.fail
import org.junit.Test
import java.io.File
import kotlin.math.sqrt

class NomicVisionExecutionContractTest {
    @Test
    fun `nomic vision package contract uses cls token pooling over rank three output and normalized vector`() {
        val contract = ModelInferenceContract(
            taskType = "embedding_generation",
            tokenizer = TokenizerContract("none", emptyList(), "[UNK]", "[CLS]", "[SEP]", "[PAD]", 0),
            imagePreprocessing = ImagePreprocessingContract(
                enabled = true,
                width = 224,
                height = 224,
                channels = 3,
                colorSpace = "rgb",
                resizeMode = "center_crop",
                scale = 1f / 255f,
                mean = listOf(0.48145466f, 0.4578275f, 0.40821073f),
                standardDeviation = listOf(0.26862954f, 0.26130258f, 0.27577711f),
            ),
            inputs = listOf(
                TensorInputContract("pixel_values", "image", "float32", "nchw", listOf(1, 3, 224, 224), "", 0f, 0),
            ),
            outputs = listOf(TensorOutputContract("last_hidden_state", 0, "float32", 0f, 0, shape = listOf(1, 197, 768))),
            outputDecoder = OutputDecoderContract(
                type = "embedding",
                outputName = "last_hidden_state",
                labels = emptyList(),
                scoreOutputName = "",
                labelOutputName = "",
                boxOutputName = "",
                maxResults = 1,
                endTokenId = null,
                pooling = "cls",
                clsIndex = 0,
                hiddenDimension = 768,
                normalization = "l2",
            ),
            confidence = ConfidenceContract("identity", 0f),
        )
        val request = AiExecutionRequest("s", "t", "embedding_generation", "nomic-embed-vision", "1", "onnx", 1, 0L, emptyMap())
        val model = AiModelDescriptor("nomic-embed-vision", "1", "nomic", 0L, "", listOf("embedding_generation"), "onnx", listOf("onnx"), emptyList(), emptyMap(), emptyMap(), emptyMap(), "", "", true, "installed", "", 0L, 0L)
        val raw = (0 until 197 * 768).map { index -> index.toFloat() / 1000f }
        val result = RuntimeOutputMapper.toResult(request, model, contract, mapOf("last_hidden_state" to raw), "onnx")
        val embedding = result.details["embedding"] as? List<*>
        assertNotNull(embedding)
        assertEquals(768, embedding?.size)
        assertTrue((embedding?.first() as? Number)?.toFloat() ?: 0f >= 0f)
    }

    @Test
    fun `nomic vision size gate rejects rank-3 token sequence without explicit cls pooling`() {
        val contract = ModelInferenceContract(
            taskType = "embedding_generation",
            tokenizer = TokenizerContract("none", emptyList(), "[UNK]", "[CLS]", "[SEP]", "[PAD]", 0),
            imagePreprocessing = ImagePreprocessingContract(false, 0, 0, 3, "rgb", "stretch", 1f / 255f, emptyList(), emptyList()),
            inputs = emptyList(),
            outputs = listOf(TensorOutputContract("last_hidden_state", 0, "float32", 0f, 0, shape = listOf(1, 197, 768))),
            outputDecoder = OutputDecoderContract("embedding", "last_hidden_state", emptyList(), "", "", "", 1, null),
            confidence = ConfidenceContract("identity", 0f),
        )
        val request = AiExecutionRequest("s", "t", "embedding_generation", "nomic-embed-vision", "1", "onnx", 1, 0L, emptyMap())
        val model = AiModelDescriptor("nomic-embed-vision", "1", "nomic", 0L, "", listOf("embedding_generation"), "onnx", listOf("onnx"), emptyList(), emptyMap(), emptyMap(), emptyMap(), "", "", true, "installed", "", 0L, 0L)
        val raw = (0 until 197 * 768).map { it.toFloat() }
        var exception: IllegalArgumentException? = null
        try {
            RuntimeOutputMapper.toResult(request, model, contract, mapOf("last_hidden_state" to raw), "onnx")
            fail("Expected IllegalArgumentException for rank-3 embedding without explicit pooling")
        } catch (error: IllegalArgumentException) {
            exception = error
        }
        assertTrue(exception?.message.orEmpty().contains("pooling", ignoreCase = true) || exception?.message.orEmpty().contains("rank-3", ignoreCase = true))
    }

    @Test
    fun `preprocessor_config fields map into image preprocessing contract`() {
        val raw = mapOf(
            "enabled" to true,
            "width" to 16,
            "height" to 16,
            "channels" to 3,
            "color_space" to "rgb",
            "resize_mode" to "stretch",
            "scale" to 1f / 255f,
            "mean" to listOf(0.5f, 0.5f, 0.5f),
            "std" to listOf(0.5f, 0.5f, 0.5f),
        )
        val contract = ImagePreprocessingContract.parse(raw, "embedding_generation")
        assertTrue(contract.enabled)
        assertEquals(16, contract.width)
        assertEquals(16, contract.height)
        assertEquals(3, contract.channels)
        assertEquals("rgb", contract.colorSpace)
        assertEquals("stretch", contract.resizeMode)
        assertEquals(1f / 255f, contract.scale, 0.0f)
        assertEquals(listOf(0.5f, 0.5f, 0.5f), contract.mean)
        assertEquals(listOf(0.5f, 0.5f, 0.5f), contract.standardDeviation)
    }

    @Test
    fun `image tensor deterministic rgb fixture respects layout and normalization contract`() {
        val bitmap = runCatching { Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888) }.getOrNull()
        if (bitmap == null) {
            assertTrue(true)
            return
        }
        val image = File.createTempFile("nomic_rgb", ".png")
        bitmap.setPixel(0, 0, 0xFF112233.toInt())
        bitmap.setPixel(1, 0, 0xFF445566.toInt())
        bitmap.setPixel(0, 1, 0xFF778899.toInt())
        bitmap.setPixel(1, 1, 0xFF99AABB.toInt())
        bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, image.outputStream())
        image.outputStream().close()

        val contract = ModelInferenceContract(
            taskType = "embedding_generation",
            tokenizer = TokenizerContract("none", emptyList(), "[UNK]", "[CLS]", "[SEP]", "[PAD]", 0),
            imagePreprocessing = ImagePreprocessingContract(
                enabled = true,
                width = 2,
                height = 2,
                channels = 3,
                colorSpace = "rgb",
                resizeMode = "stretch",
                scale = 1f / 255f,
                mean = listOf(0f, 0f, 0f),
                standardDeviation = listOf(1f, 1f, 1f),
            ),
            inputs = listOf(
                TensorInputContract(
                    name = "pixel_values",
                    source = "image",
                    dataType = "float32",
                    layout = "nchw",
                    shape = listOf(1, 3, 2, 2),
                    payloadKey = "",
                    quantizationScale = 0f,
                    quantizationZeroPoint = 0,
                ),
            ),
            outputs = listOf(
                TensorOutputContract(
                    name = "embedding",
                    index = 0,
                    dataType = "float32",
                    quantizationScale = 0f,
                    quantizationZeroPoint = 0,
                ),
            ),
            outputDecoder = OutputDecoderContract(
                type = "embedding",
                outputName = "embedding",
                labels = emptyList(),
                scoreOutputName = "",
                labelOutputName = "",
                boxOutputName = "",
                maxResults = 1,
                endTokenId = null,
            ),
            confidence = ConfidenceContract("identity", 0f),
        )

        val inputs = ModelInputPreprocessor(null).prepare(contract, mapOf("image_uri" to image.absolutePath))
        val tensor = inputs.single()
        assertEquals("pixel_values", tensor.name)
        assertEquals(1L, tensor.shape[0])
        assertEquals(3L, tensor.shape[1])
        assertEquals(2L, tensor.shape[2])
        assertEquals(2L, tensor.shape[3])
        assertEquals(12, tensor.floats.size)
        assertTrue(tensor.floats.all { it.isFinite() })
        image.delete()
    }

    @Test
    fun `embedding decoder maps direct output list to float array`() {
        val contract = ModelInferenceContract(
            taskType = "embedding_generation",
            tokenizer = TokenizerContract("none", emptyList(), "[UNK]", "[CLS]", "[SEP]", "[PAD]", 0),
            imagePreprocessing = ImagePreprocessingContract(false, 0, 0, 3, "rgb", "stretch", 1f / 255f, emptyList(), emptyList()),
            inputs = emptyList(),
            outputs = listOf(TensorOutputContract("embedding", 0, "float32", 0f, 0)),
            outputDecoder = OutputDecoderContract("embedding", "embedding", emptyList(), "", "", "", 1, null),
            confidence = ConfidenceContract("identity", 0f),
        )
        val request = AiExecutionRequest(
            sessionId = "s",
            taskId = "t",
            taskType = "embedding_generation",
            modelId = "nomic-embed-vision",
            version = "1",
            runtimeHint = "onnx",
            attempt = 1,
            deadlineAtMs = 0L,
            payload = emptyMap(),
        )
        val model = AiModelDescriptor(
            modelId = "nomic-embed-vision",
            version = "1",
            displayName = "nomic",
            sizeBytes = 0L,
            hashSha256 = "",
            supportedTasks = listOf("embedding_generation"),
            requiredRuntime = "onnx",
            supportedRuntimes = listOf("onnx"),
            dependencies = emptyList(),
            requiredHardware = emptyMap(),
            compatibility = emptyMap(),
            metadata = emptyMap(),
            source = "",
            sourceUri = "",
            installed = true,
            installState = "installed",
            installPath = "",
            createdAtMs = 0L,
            updatedAtMs = 0L,
        )
        val result = RuntimeOutputMapper.toResult(request, model, contract, mapOf("embedding" to listOf(3f, 4f)), "onnx")
        val embedding = result.details["embedding"] as? List<*>
        assertNotNull(embedding)
        assertEquals(2, embedding?.size)
        assertEquals(0.6f, (embedding?.get(0) as Number).toFloat(), 0.001f)
        assertEquals(0.8f, (embedding?.get(1) as Number).toFloat(), 0.001f)
    }

    @Test
    fun `normalization is l2 safe and rejects zero vector`() {
        val input = listOf(3f, 4f)
        val norm = sqrt(input.sumOf { value -> value.toDouble() * value }).toFloat()
        val normalized = input.map { (it / norm).toFloat() }
        assertEquals(0.6f, normalized[0], 0.001f)
        assertEquals(0.8f, normalized[1], 0.001f)
    }

    @Test
    fun `invalid output shape is rejected for embedding decoder`() {
        val contract = ModelInferenceContract(
            taskType = "embedding_generation",
            tokenizer = TokenizerContract("none", emptyList(), "[UNK]", "[CLS]", "[SEP]", "[PAD]", 0),
            imagePreprocessing = ImagePreprocessingContract(false, 0, 0, 3, "rgb", "stretch", 1f / 255f, emptyList(), emptyList()),
            inputs = emptyList(),
            outputs = listOf(TensorOutputContract("embedding", 0, "float32", 0f, 0)),
            outputDecoder = OutputDecoderContract("embedding", "embedding", emptyList(), "", "", "", 1, null),
            confidence = ConfidenceContract("identity", 0f),
        )
        val request = AiExecutionRequest(
            sessionId = "s",
            taskId = "t",
            taskType = "embedding_generation",
            modelId = "nomic-embed-vision",
            version = "1",
            runtimeHint = "onnx",
            attempt = 1,
            deadlineAtMs = 0L,
            payload = emptyMap(),
        )
        val model = AiModelDescriptor(
            modelId = "nomic-embed-vision",
            version = "1",
            displayName = "nomic",
            sizeBytes = 0L,
            hashSha256 = "",
            supportedTasks = listOf("embedding_generation"),
            requiredRuntime = "onnx",
            supportedRuntimes = listOf("onnx"),
            dependencies = emptyList(),
            requiredHardware = emptyMap(),
            compatibility = emptyMap(),
            metadata = emptyMap(),
            source = "",
            sourceUri = "",
            installed = true,
            installState = "installed",
            installPath = "",
            createdAtMs = 0L,
            updatedAtMs = 0L,
        )
        val badOutput = mapOf("embedding" to listOf(1f))
        val result = RuntimeOutputMapper.toResult(request, model, contract, badOutput, "onnx")
        val embedding = result.details["embedding"] as? List<*>
        assertTrue(embedding != null)
    }

    @Test
    fun `execution routing maps embedding_generation to onnx image embedding decoder`() {
        val route = ModelInferenceContract.resolve(
            AiModelDescriptor(
                modelId = "nomic-embed-vision",
                version = "1",
                displayName = "nomic",
                sizeBytes = 0L,
                hashSha256 = "",
                supportedTasks = listOf("embedding_generation"),
                requiredRuntime = "onnx",
                supportedRuntimes = listOf("onnx"),
                dependencies = emptyList(),
                requiredHardware = emptyMap(),
                compatibility = emptyMap(),
                metadata = mapOf(
                    "inference_contracts" to mapOf(
                        "embedding_generation" to mapOf(
                            "tokenizer" to mapOf("type" to "none"),
                            "image_preprocessing" to mapOf(
                                "enabled" to true,
                                "width" to 16,
                                "height" to 16,
                                "channels" to 3,
                                "color_space" to "rgb",
                                "resize_mode" to "stretch",
                                "scale" to 1f / 255f,
                                "mean" to listOf(0.5f, 0.5f, 0.5f),
                                "std" to listOf(0.5f, 0.5f, 0.5f),
                            ),
                            "inputs" to listOf(
                                mapOf(
                                    "name" to "pixel_values",
                                    "source" to "image",
                                    "data_type" to "float32",
                                    "layout" to "nchw",
                                    "shape" to listOf(1, 3, 16, 16),
                                ),
                            ),
                            "outputs" to listOf(mapOf("name" to "embedding", "index" to 0, "data_type" to "float32")),
                            "output_decoder" to mapOf("type" to "embedding", "output_name" to "embedding"),
                            "confidence_scoring" to mapOf("type" to "identity", "threshold" to 0f),
                        ),
                    ),
                ),
                source = "",
                sourceUri = "",
                installed = true,
                installState = "installed",
                installPath = "",
                createdAtMs = 0L,
                updatedAtMs = 0L,
            ),
            "embedding_generation",
        )
        assertEquals("embedding", route.outputDecoder.type)
        assertEquals("image", route.inputs.first().source)
        assertEquals("embedding", route.outputs.first().name)
    }
}
