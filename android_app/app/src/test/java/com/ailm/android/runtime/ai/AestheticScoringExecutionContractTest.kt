package com.ailm.android.runtime.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

class AestheticScoringExecutionContractTest {
    private val packageDirectory = TestPackageFixtureResolver.resolvePackageDirectory(
        packageName = "aesthetic_predictor_v2.5",
        zipName = "aesthetic_predictor_v2.5.zip",
    )

    @Test
    fun `real package is recognized as aesthetic scoring but not ready without preprocessing`() {
        val inspection = ModelPackageInspector().inspect(packageDirectory, File("build/aesthetic-extracted"))
        assertEquals("onnx", inspection.runtime)
        assertTrue(inspection.supportedTasks.contains("aesthetic_scoring"))
        assertTrue(inspection.valid)
        assertTrue(inspection.issues.any { it.code == "preprocessing_contract_unresolved" })
        assertFalse(inspection.issues.any { it.code == "model_artifact_missing" || it.code == "execution_task_missing" })
    }

    @Test
    fun `scalar decoder preserves raw aesthetic score and selects canonical output`() {
        val contract = contract()
        val result = RuntimeOutputMapper.toResult(
            AiExecutionRequest("s", "t", "aesthetic_scoring", "aesthetic_predictor_v2.5", "1", "onnx", 1, 0L, emptyMap()),
            descriptor(),
            contract,
            mapOf("output" to listOf(7.25f), "onnx::ReduceL2_3786" to List(1152) { 1f }),
            "onnx",
        )
        assertEquals(7.25f, result.details["score"])
        assertEquals(7.25f, result.details["aesthetic_score"])
    }

    @Test
    fun `aesthetic output rejects incompatible shapes`() {
        val contract = contract().copy(
            outputs = listOf(TensorOutputContract("output", 0, "float32", 0f, 0, listOf(1, 2))),
        )
        try {
            RuntimeOutputMapper.toResult(
                AiExecutionRequest("s", "t", "aesthetic_scoring", "aesthetic_predictor_v2.5", "1", "onnx", 1, 0L, emptyMap()),
                descriptor(),
                contract,
                mapOf("output" to listOf(7.25f)),
                "onnx",
            )
            fail("Expected incompatible aesthetic output shape to be rejected")
        } catch (_: IllegalArgumentException) {
            // Expected contract rejection.
        }
    }

    @Test
    fun `aesthetic decoder is regression not classification or embedding`() {
        assertEquals("regression", contract().outputDecoder.type)
        assertTrue(contract().outputDecoder.labels.isEmpty())
        assertEquals("output", contract().outputDecoder.outputName)
    }

    private fun contract(): ModelInferenceContract = ModelInferenceContract(
        taskType = "aesthetic_scoring",
        tokenizer = TokenizerContract("none", emptyList(), "[UNK]", "[CLS]", "[SEP]", "[PAD]", 0),
        imagePreprocessing = ImagePreprocessingContract(false, 0, 0, 3, "rgb", "stretch", 1f / 255f, emptyList(), emptyList()),
        inputs = listOf(TensorInputContract("input", "image", "float32", "nchw", listOf(1, 3, 384, 384), "image_uri", 0f, 0)),
        outputs = listOf(
            TensorOutputContract("output", 0, "float32", 0f, 0, listOf(1, 1)),
            TensorOutputContract("onnx::ReduceL2_3786", 1, "float32", 0f, 0, listOf(1, 1152)),
        ),
        outputDecoder = OutputDecoderContract("regression", "output", emptyList(), "", "", "", 1, null, hiddenDimension = 1),
        confidence = ConfidenceContract("identity", 0f),
    )

    private fun descriptor(): AiModelDescriptor = AiModelDescriptor(
        "aesthetic_predictor_v2.5", "1", "Aesthetic Predictor v2.5", 0L, "", listOf("aesthetic_scoring"), "onnx", listOf("onnx"),
        emptyList(), emptyMap(), emptyMap(), emptyMap(), "", "", true, "installed", "", 0L, 0L,
    )
}
