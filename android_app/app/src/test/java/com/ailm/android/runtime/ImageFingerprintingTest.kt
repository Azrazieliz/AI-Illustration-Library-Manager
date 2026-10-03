package com.ailm.android.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ImageFingerprintingTest {
    @Test
    fun `perceptual hash distance counts changed bits`() {
        assertEquals(
            4,
            ImageFingerprinting.perceptualHashDistance(
                "00000000000000000000000000000000",
                "0000000000000000000000000000000f",
            ),
        )
    }

    @Test
    fun `conservative visual duplicate ignores filenames and accepts tiny hash drift`() {
        val current = ImageFingerprint(
            sha256 = "current",
            perceptualHash = "00000000000000000000000000000000",
            width = 1920,
            height = 1080,
            sizeBytes = 900_000,
        )
        val candidate = ImageFingerprintMatch(
            imageId = 1,
            uri = "content://old",
            filename = "totally-different-name.jpg",
            perceptualHash = "00000000000000000000000000000003",
            width = 1920,
            height = 1080,
            sizeBytes = 850_000,
        )

        assertTrue(ImageFingerprinting.isConservativeVisualDuplicate(current, candidate))
    }

    @Test
    fun `different dimensions are not auto deleted as visual duplicates`() {
        val current = ImageFingerprint(
            sha256 = "current",
            perceptualHash = "00000000000000000000000000000000",
            width = 1920,
            height = 1080,
            sizeBytes = 900_000,
        )
        val candidate = ImageFingerprintMatch(
            imageId = 1,
            uri = "content://old",
            filename = "resized.jpg",
            perceptualHash = "00000000000000000000000000000000",
            width = 1280,
            height = 720,
            sizeBytes = 450_000,
        )

        assertFalse(ImageFingerprinting.isConservativeVisualDuplicate(current, candidate))
    }
}
