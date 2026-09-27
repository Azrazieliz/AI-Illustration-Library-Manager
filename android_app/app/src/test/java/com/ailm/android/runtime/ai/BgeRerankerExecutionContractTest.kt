package com.ailm.android.runtime.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

class BgeRerankerExecutionContractTest {
    private val packageDirectory = TestPackageFixtureResolver.resolvePackageDirectory(
        packageName = "BGE-Reranker-v2-m3",
        zipName = "BGE-Reranker-v2-m3.zip",
    )
    private val contract by lazy { contractFromRealPackage() }

    @Test
    fun `reranking output decoder parses for text reranking task`() {
        val decoder = OutputDecoderContract.parse(
            mapOf(
                "type" to "reranking",
                "output_name" to "logits",
                "hidden_dimension" to 1,
            ),
            "text_reranking",
        )
        assertEquals("reranking", decoder.type)
        assertEquals("logits", decoder.outputName)
    }

    @Test
    fun `real package resolves XLM-R reranking contract`() {
        check(packageDirectory.isDirectory)
        assertEquals(listOf("input_ids", "attention_mask"), contract.inputs.map { it.name })
        assertTrue(contract.inputs.none { it.name == "token_type_ids" })
        assertEquals("reranking", contract.outputDecoder.type)
        assertEquals("logits", contract.outputDecoder.outputName)
        assertEquals(listOf(1, 1), contract.outputs.single().shape)
        assertEquals("unigram", contract.tokenizer.type)
        assertEquals("xlm_roberta", contract.tokenizer.pairTemplate)
    }

    @Test
    fun `real tokenizer encodes query document pair with package template`() {
        val tensors = ModelInputPreprocessor(null).prepare(
            contract,
            mapOf("query" to "hello", "document" to "world"),
        )
        val ids = tensors.first { it.name == "input_ids" }
        val mask = tensors.first { it.name == "attention_mask" }
        assertEquals(longArrayOf(1, 8192).toList(), ids.shape.toList())
        assertEquals(0L, ids.longs.first())
        val active = ids.longs.take(mask.longs.count { it == 1L })
        assertEquals("active=$active", 3, active.count { it == 2L })
        assertEquals(2L, active.last())
        assertEquals(1L, mask.longs.first())
        assertEquals(0L, mask.longs.last())
        assertFalse(tensors.any { it.name == "token_type_ids" })
    }

    @Test
    fun `reranker output preserves raw scalar logit`() {
        val result = RuntimeOutputMapper.toResult(
            request = AiExecutionRequest("s", "t", "text_reranking", "bge-reranker-v2-m3", "1", "onnx", 1, 0L, mapOf("query" to "q", "document" to "d")),
            model = descriptor(contract),
            contract = contract,
            outputs = mapOf("logits" to listOf(2.75f)),
            runtimeId = "onnx",
        )
        assertEquals(2.75f, result.details["logit"])
        assertEquals(2.75f, result.details["score"])
    }

    @Test
    fun `reranker rejects non scalar output shape`() {
        val contract = contract.copy(
            outputs = listOf(TensorOutputContract("logits", 0, "float32", 0f, 0, listOf(1, 2))),
        )
        try {
            RuntimeOutputMapper.toResult(
                AiExecutionRequest("s", "t", "text_reranking", "bge-reranker-v2-m3", "1", "onnx", 1, 0L, emptyMap()),
                descriptor(contract),
                contract,
                mapOf("logits" to listOf(2.75f)),
                "onnx",
            )
            fail("Expected incompatible reranking output shape to be rejected")
        } catch (_: IllegalArgumentException) {
            // Expected contract rejection.
        }
    }

    private fun contractFromRealPackage(): ModelInferenceContract {
        check(packageDirectory.isDirectory) { "Missing real BGE package at ${packageDirectory.absolutePath}" }
        val tokenizerJson = LocalAiJson.decodeMap(File(packageDirectory, "tokenizer.json").readText())
        val model = (tokenizerJson["model"] as? Map<*, *>)?.mapNotNull { (key, value) ->
            key?.toString()?.let { textKey -> value?.let { textKey to it } }
        }?.toMap() ?: error("Missing tokenizer model")
        val vocabularyEntries = (model["vocab"] as? List<*>)?.mapNotNull { value ->
            val pair = value as? List<*> ?: return@mapNotNull null
            val token = pair.getOrNull(0)?.toString() ?: return@mapNotNull null
            val score = (pair.getOrNull(1) as? Number)?.toFloat() ?: return@mapNotNull null
            token to score
        }.orEmpty()
        check(vocabularyEntries.isNotEmpty())
        return ModelInferenceContract(
            taskType = "text_reranking",
            tokenizer = TokenizerContract(
                type = "unigram",
                vocabulary = vocabularyEntries.map { it.first },
                unknownToken = "<unk>",
                startToken = "<s>",
                endToken = "</s>",
                padToken = "<pad>",
                maxLength = 8192,
                modelType = "Unigram",
                normalizer = "precompiled",
                preTokenizer = "metaspace",
                vocabularyScores = vocabularyEntries.map { it.second },
                pairTemplate = "xlm_roberta",
            ),
            imagePreprocessing = ImagePreprocessingContract(false, 0, 0, 0, "rgb", "stretch", 1f / 255f, emptyList(), emptyList()),
            inputs = listOf(
                TensorInputContract("input_ids", "text_ids", "int64", "sequence", listOf(1, -1), "query", 0f, 0),
                TensorInputContract("attention_mask", "attention_mask", "int64", "sequence", listOf(1, -1), "", 0f, 0),
            ),
            outputs = listOf(TensorOutputContract("logits", 0, "float32", 0f, 0, listOf(1, 1))),
            outputDecoder = OutputDecoderContract("reranking", "logits", emptyList(), "", "", "", 1, null, hiddenDimension = 1),
            confidence = ConfidenceContract("identity", 0f),
        )
    }

    private fun descriptor(contract: ModelInferenceContract): AiModelDescriptor = AiModelDescriptor(
        modelId = "bge-reranker-v2-m3",
        version = "1",
        displayName = "BGE Reranker v2 m3",
        sizeBytes = 0L,
        hashSha256 = "",
        supportedTasks = listOf("text_reranking"),
        requiredRuntime = "onnx",
        supportedRuntimes = listOf("onnx"),
        dependencies = emptyList(),
        requiredHardware = emptyMap(),
        compatibility = emptyMap(),
        metadata = mapOf("inference_contracts" to mapOf("text_reranking" to emptyMap<String, Any>())),
        source = "",
        sourceUri = "",
        installed = true,
        installState = "installed",
        installPath = "",
        createdAtMs = 0L,
        updatedAtMs = 0L,
    )
}
