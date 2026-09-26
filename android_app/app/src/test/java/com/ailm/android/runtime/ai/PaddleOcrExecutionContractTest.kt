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
        assertFalse(inspection.valid)
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
    fun `dictionary count and unresolved CTC mapping remain explicit`() {
        val dictionary = inspectPackage().metadata["ocr_dictionary"] as Map<*, *>
        assertEquals(18383, dictionary["entry_count"])
        assertEquals(18385, dictionary["recognizer_class_count"])
        assertEquals("unresolved", dictionary["mapping_status"])
        assertTrue(inspectPackage().issues.any { it.code == "ocr_ctc_mapping_unresolved" })
    }

    @Test
    fun `OCR is not executable without proven preprocessing and postprocessing`() {
        val issues = inspectPackage().issues.map { it.code }.toSet()
        assertTrue(issues.contains("ocr_preprocessing_unresolved"))
        assertTrue(issues.contains("ocr_detector_postprocessing_unresolved"))
        assertFalse(inspectPackage().valid)
    }

    private fun inspectPackage(): ModelPackageInspection =
        ModelPackageInspector().inspect(packageDirectory, File("build/paddleocr-extracted"))
}
