package com.ailm.android.runtime.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalAiActivationRegressionTest {

    @Test
    fun `active model settings are exposed at top level after persistence`() {
        val settings = AiSettings(
            extra = mapOf(
                "active_model_id" to "asterioncore_qwen",
                "active_model_version" to "1.0.0",
                "active_model_id.embedding_generation" to "asterioncore_nomic",
            ),
        )

        val mapped = settings.toMap()

        assertEquals("asterioncore_qwen", mapped["active_model_id"])
        assertEquals("1.0.0", mapped["active_model_version"])
        assertEquals("asterioncore_nomic", mapped["active_model_id.embedding_generation"])
        assertTrue(mapped["extra"] is Map<*, *>)
    }

    @Test
    fun `new extracted package verifies against artifact hash not zip hash`() {
        val model = descriptor(
            descriptorHash = "artifact",
            metadata = mapOf(
                "package_hash_sha256" to "package",
                "artifact_hash_sha256" to "artifact",
            ),
        )

        assertEquals("artifact", expectedInstalledArtifactHash(model))
    }

    @Test
    fun `legacy zip package hash is not compared to extracted artifact`() {
        val model = descriptor(
            descriptorHash = "package",
            metadata = mapOf("package_hash_sha256" to "package"),
        )

        assertEquals("", expectedInstalledArtifactHash(model))
    }

    @Test
    fun `direct artifact keeps descriptor hash verification`() {
        val model = descriptor(
            descriptorHash = "direct-artifact",
            metadata = emptyMap(),
        )

        assertEquals("direct-artifact", expectedInstalledArtifactHash(model))
    }

    private fun descriptor(
        descriptorHash: String,
        metadata: Map<String, Any>,
    ): AiModelDescriptor {
        return AiModelDescriptor(
            modelId = "test-model",
            version = "1.0.0",
            displayName = "Test model",
            sizeBytes = 1L,
            hashSha256 = descriptorHash,
            supportedTasks = listOf("embedding_generation"),
            requiredRuntime = "onnx",
            supportedRuntimes = listOf("onnx"),
            dependencies = emptyList(),
            requiredHardware = emptyMap(),
            compatibility = emptyMap(),
            metadata = metadata,
            source = "local",
            sourceUri = "",
            installed = true,
            installState = "installed",
            installPath = "/tmp/model.onnx",
            createdAtMs = 0L,
            updatedAtMs = 0L,
        )
    }
}
