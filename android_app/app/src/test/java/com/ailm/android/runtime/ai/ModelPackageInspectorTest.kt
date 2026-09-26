package com.ailm.android.runtime.ai

import ai.onnxruntime.NodeInfo
import ai.onnxruntime.ValueInfo
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class ModelPackageInspectorTest {

    private fun withTempDir(block: (File) -> Unit) {
        val dir = createTempDir(prefix = "mpi-test-")
        try {
            block(dir)
        } finally {
            dir.deleteRecursively()
        }
    }

    private fun callResolveArtifact(packageRoot: File, files: List<File>, metadata: Map<String, Any>): Pair<File?, List<ModelPackageIssue>> {
        val inspector = ModelPackageInspector()
        val issues = mutableListOf<ModelPackageIssue>()
        val method = ModelPackageInspector::class.java.getDeclaredMethod("resolveArtifact", File::class.java, File::class.java, List::class.java, Map::class.java, MutableList::class.java)
        method.isAccessible = true
        val result = method.invoke(inspector, packageRoot, packageRoot, files, metadata, issues) as File?
        return result to issues.toList()
    }

    @Test
    fun `onnx runtime nodeinfo constructor remains compatible with native api`() {
        val ctor = NodeInfo::class.java.getDeclaredConstructor(String::class.java, ValueInfo::class.java)
        assertNotNull(ctor)
        assertTrue(ctor.isAccessible || ctor.modifiers and 1 == 1)
    }

    @Test
    fun `single onnx at root resolves`() {
        withTempDir { root ->
            val model = File(root, "model.onnx")
            model.writeText("dummy")
            val (resolved, issues) = callResolveArtifact(root, listOf(model), emptyMap())
            assertNotNull(resolved)
            assertEquals(model.canonicalPath, resolved!!.canonicalPath)
            assertTrue(issues.isEmpty())
        }
    }

    @Test
    fun `single onnx in top-level folder resolves`() {
        withTempDir { root ->
            val sub = File(root, "package")
            sub.mkdirs()
            val model = File(sub, "m.onnx")
            model.writeText("dummy")
            val files = listOf(model)
            val (resolved, issues) = callResolveArtifact(root, files, emptyMap())
            assertNotNull(resolved)
            assertEquals(model.canonicalPath, resolved!!.canonicalPath)
            assertTrue(issues.isEmpty())
        }
    }

    @Test
    fun `multiple onnx without model_file is ambiguous`() {
        withTempDir { root ->
            val a = File(root, "a.onnx"); a.writeText("x")
            val b = File(root, "b.onnx"); b.writeText("y")
            val (resolved, issues) = callResolveArtifact(root, listOf(a, b), emptyMap())
            assertNull(resolved)
            assertTrue(issues.any { it.code == "model_artifact_ambiguous" })
        }
    }

    @Test
    fun `multiple onnx with valid model_file selects specified`() {
        withTempDir { root ->
            val modelsDir = File(root, "models")
            modelsDir.mkdirs()
            val a = File(modelsDir, "a.onnx"); a.writeText("x")
            val b = File(modelsDir, "b.onnx"); b.writeText("y")
            val metadata = mapOf("model_file" to "models/b.onnx")
            val (resolved, issues) = callResolveArtifact(root, listOf(a, b), metadata)
            assertNotNull(resolved)
            assertEquals(b.canonicalPath, resolved!!.canonicalPath)
            assertTrue(issues.isEmpty())
        }
    }

    @Test
    fun `invalid model_file produces error`() {
        withTempDir { root ->
            val a = File(root, "a.onnx"); a.writeText("x")
            val metadata = mapOf("model_file" to "missing.onnx")
            val (resolved, issues) = callResolveArtifact(root, listOf(a), metadata)
            assertNull(resolved)
            assertTrue(issues.any { it.code == "model_artifact_reference_invalid" })
        }
    }

    @Test
    fun `safetensors-only package reported unsupported`() {
        withTempDir { root ->
            val s = File(root, "model.safetensors")
            s.writeText("x")
            val (resolved, issues) = callResolveArtifact(root, listOf(s), emptyMap())
            assertNull(resolved)
            assertTrue(issues.any { it.code == "unsupported_model_format" })
        }
    }

    @Test
    fun `tflite package resolves`() {
        withTempDir { root ->
            val t = File(root, "model.tflite")
            t.writeText("x")
            val (resolved, issues) = callResolveArtifact(root, listOf(t), emptyMap())
            assertNotNull(resolved)
            assertEquals(t.canonicalPath, resolved!!.canonicalPath)
            assertTrue(issues.isEmpty())
        }
    }

    @Test
    fun `gguf-only package is recognized as valid LLAMA_CPP artifact`() {
        withTempDir { root ->
            val g = File(root, "model.gguf")
            g.writeText("x")
            val (resolved, issues) = callResolveArtifact(root, listOf(g), emptyMap())
            assertNotNull("GGUF should be recognized as valid artifact", resolved)
            assertEquals("GGUF should stay artifact-backed by a gguf file extension", "gguf", resolved?.extension?.lowercase())
            assertFalse("GGUF should not have unsupported format issues", issues.any { it.code == "unsupported_model_format" })
        }
    }

    @Test
    fun `multi-artifact with model_artifacts metadata resolves`() {
        withTempDir { root ->
            val encoder = File(root, "encoder.onnx"); encoder.writeText("e")
            val decoder = File(root, "decoder.onnx"); decoder.writeText("d")
            val metadata = linkedMapOf<String, Any>(
                "model_artifacts" to listOf(
                    mapOf("path" to "encoder.onnx"),
                    mapOf("path" to "decoder.onnx")
                )
            )
            val (resolved, issues) = callResolveArtifact(root, listOf(encoder, decoder), metadata as Map<String, Any>)
            assertNotNull("Multi-artifact with metadata should resolve to first artifact", resolved)
            assertTrue("Multi-artifact with valid metadata should not have issues", issues.isEmpty())
        }
    }

    @Test
    fun `multiple artifacts without model_artifacts metadata is ambiguous`() {
        withTempDir { root ->
            val encoder = File(root, "encoder.onnx"); encoder.writeText("e")
            val decoder = File(root, "decoder.onnx"); decoder.writeText("d")
            val (resolved, issues) = callResolveArtifact(root, listOf(encoder, decoder), emptyMap())
            assertNull("Multiple artifacts without metadata should not resolve", resolved)
            assertTrue("Should report ambiguous artifacts", issues.any { it.code == "model_artifact_ambiguous" })
        }
    }

    @Test
    fun `invalid model_artifacts reference produces error`() {
        withTempDir { root ->
            val encoder = File(root, "encoder.onnx"); encoder.writeText("e")
            val metadata = linkedMapOf<String, Any>(
                "model_artifacts" to listOf(
                    mapOf("path" to "encoder.onnx"),
                    mapOf("path" to "missing_decoder.onnx")
                )
            )
            val (resolved, issues) = callResolveArtifact(root, listOf(encoder), metadata as Map<String, Any>)
            assertNull("Invalid artifact references should not resolve", resolved)
            assertTrue("Should report invalid artifacts", issues.any { it.code == "model_artifacts_reference_invalid" })
        }
    }
}
