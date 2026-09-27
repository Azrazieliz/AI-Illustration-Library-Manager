package com.ailm.android.runtime.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PaddleOcrRuntimeTest {

    @Test
    fun `CTC decoder removes blanks and repeated classes with dictionary offset one`() {
        val dictionary = listOf("A", "B")
        val classCount = 4 // blank + A + B + appended space
        val logits = listOf(
            9f, 0f, 0f, 0f,  // blank
            0f, 9f, 0f, 0f,  // A
            0f, 8f, 0f, 0f,  // repeated A
            9f, 0f, 0f, 0f,  // blank
            0f, 0f, 9f, 0f,  // B
            0f, 0f, 0f, 9f,  // space
        )

        val decoded = PaddleOcrCtcDecoder.decode(
            logits = logits,
            classCount = classCount,
            dictionary = dictionary,
        )

        assertEquals("AB ", decoded.text)
        assertTrue(decoded.confidence > 0f)
    }

    @Test
    fun `DB compatible postprocessor thresholds scores and unclipping expands box`() {
        val width = 8
        val height = 8
        val values = MutableList(width * height) { 0f }
        for (y in 2..4) {
            for (x in 2..5) {
                values[y * width + x] = 0.95f
            }
        }

        val boxes = PaddleOcrDbPostProcessor.boxes(
            probabilities = values,
            width = width,
            height = height,
            sourceWidth = 80,
            sourceHeight = 80,
            threshold = 0.3f,
            boxThreshold = 0.6f,
            unclipRatio = 1.5f,
        )

        assertEquals(1, boxes.size)
        val box = boxes.single()
        assertTrue(box.left < 20)
        assertTrue(box.top < 20)
        assertTrue(box.right > 50)
        assertTrue(box.bottom > 40)
        assertTrue(box.score >= 0.9f)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `CTC decoder rejects dictionary class mismatch`() {
        PaddleOcrCtcDecoder.decode(
            logits = List(8) { 0f },
            classCount = 4,
            dictionary = listOf("only-one-character"),
        )
    }
}
