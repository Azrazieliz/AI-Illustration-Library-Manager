package com.ailm.android.runtime.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class PaddleOcrExecutionContractTest {
    private val packageDirectory = TestPackageFixtureResolver.resolvePackageDirectory(
        packageName = "PaddleOCR",
        zipName = "PaddleOCR.zip",
    )

    @Test
    fun `real package resolves one OCR package with deterministic roles`() {
        val inspection = inspectPackage()
        val roles = (inspection.metadata["model_artifacts"] as? List<*>)
            .orEmpty()
            .mapNotNull { (it as? Map<*, *>)?.get("role")?.toString() }
        assertEquals(listOf("detector", "recognizer", "dictionary_decoder"), roles)
        assertTrue(inspection.supportedTasks.contains("ocr"))
        assertFalse(inspection.issues.any { it.code == "model_artifact_ambiguous" })
        assertTrue(inspection.valid)
    }

    @Test
    fun `verified detector and recognizer graph contracts are preserved`() {
        val graph = inspectPackage().metadata["ocr_graph_contract"] as Map<*, *>
        val detector = graph["detector"] as Map<*, *>
        val detectorInput = detector["input"] as Map<*, *>
        val detectorOutput = detector["output"] as Map<*, *>
        assertEquals("x", detectorInput["name"])
        assertEquals("float32", detectorInput["data_type"])
        assertEquals(listOf(-1, 3, -1, -1), detectorInput["shape"])
        assertEquals("fetch_name_0", detectorOutput["name"])
        assertEquals(listOf(-1, 1, -1, -1), detectorOutput["shape"])

        val recognizer = graph["recognizer"] as Map<*, *>
        val recognizerInput = recognizer["input"] as Map<*, *>
        val recognizerOutput = recognizer["output"] as Map<*, *>
        assertEquals(listOf(-1, 3, 48, -1), recognizerInput["shape"])
        assertEquals(listOf(-1, -1, 18385), recognizerOutput["shape"])
    }

    @Test
    fun `dictionary count resolves canonical PP-OCRv5 CTC mapping`() {
        val dictionary = inspectPackage().metadata["ocr_dictionary"] as Map<*, *>
        assertEquals(18383, dictionary["entry_count"])
        assertEquals(18385, dictionary["recognizer_class_count"])
        assertEquals(0, dictionary["blank_index"])
        assertEquals(1, dictionary["dictionary_offset"])
        assertEquals(18384, dictionary["space_index"])
        assertEquals("ctc_blank_plus_dictionary_plus_space", dictionary["mapping_status"])
        assertFalse(inspectPackage().issues.any { it.code == "ocr_ctc_mapping_unresolved" })
    }

    @Test
    fun `OCR package exposes complete two stage runtime profile`() {
        val inspection = inspectPackage()
        assertTrue(inspection.valid)
        assertTrue(inspection.metadata["execution_readiness"] == null)
        val paddle = inspection.metadata["paddle_ocr"] as Map<*, *>
        val detectorPost = paddle["detector_postprocessing"] as Map<*, *>
        assertEquals("db", detectorPost["type"])
        assertEquals(0.3f, detectorPost["thresh"])
        assertEquals(0.6f, detectorPost["box_thresh"])
        assertEquals(1.5f, detectorPost["unclip_ratio"])
        val recognizerPre = paddle["recognizer_preprocessing"] as Map<*, *>
        assertEquals(48, recognizerPre["height"])
        assertEquals(320, recognizerPre["max_width"])
    }

    private fun inspectPackage(): ModelPackageInspection =
        ModelPackageInspector().inspect(packageDirectory, File("build/paddleocr-extracted"))
}
