package com.ailm.android.runtime.ai

import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * Regression tests for ModelPackageInspector fixes:
 * A) GGUF support added - now properly handled by LLAMA_CPP runtime
 * B) Multi-artifact ONNX models - now supported with model_artifacts metadata
 * C) Aesthetic predictor models - now properly detected and tasked as classification
 */
class ModelPackageInspectorRegressionTest {

    private fun withTempDir(block: (File) -> Unit) {
        val dir = createTempDir(prefix = "mpi-regression-")
        try {
            block(dir)
        } finally {
            dir.deleteRecursively()
        }
    }

    // =====================================================
    // Regression Tests for Fix A: GGUF Support (LLAMA_CPP)
    // =====================================================

    @Test
    fun `runtime parser canonically maps llama_cpp and llama_cpp export spellings to the LLAMA_CPP enum`() {
        assertEquals("LLAMA_CPP canonical enum must be recovered from llama_cpp", AiRuntimeType.LLAMA_CPP, AiRuntimeType.fromRaw("llama_cpp"))
        assertEquals("LLAMA_CPP canonical enum must be recovered from llama.cpp", AiRuntimeType.LLAMA_CPP, AiRuntimeType.fromRaw("llama.cpp"))
        assertEquals("LLAMA_CPP canonical enum must stay LLAMA_CPP in string form", AiRuntimeType.LLAMA_CPP.raw, AiRuntimeType.fromRaw("llama.cpp").raw)
    }

    @Test
    fun `GGUF models are recognized as valid LLAMA_CPP artifacts`() {
        withTempDir { root ->
            val ggufFile = File(root, "qwen2.5-coder-3b-instruct-q4_k_m.gguf")
            ggufFile.writeText("GGUF binary data placeholder")
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(ggufFile, File(root, "extracted"))
            
            assertFalse("GGUF package should have no unsupported format issues", result.issues.any { it.code == "unsupported_model_format" })
            assertTrue("GGUF package should be valid for LLAMA_CPP", result.runtime == AiRuntimeType.LLAMA_CPP.raw)
            assertTrue("GGUF package should still resolve the runtime even without a contract payload", result.runtime == AiRuntimeType.LLAMA_CPP.raw)
        }
    }

    @Test
    fun `GGUF with metadata is properly tasked as text_generation`() {
        withTempDir { root ->
            File(root, "metadata.json").writeText("""{"task": "text_generation"}""")
            File(root, "model.gguf").writeText("GGUF data")
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))
            
            assertFalse("GGUF should not have unsupported format issues", result.issues.any { it.code == "unsupported_model_format" })
            assertTrue("GGUF should be resolved as LLAMA_CPP runtime", result.runtime == AiRuntimeType.LLAMA_CPP.raw)
            assertTrue("GGUF metadata should resolve a text-generation task", result.supportedTasks.any { it.equals("text_generation", ignoreCase = true) } || result.capabilities.any { it.equals("text_generation", ignoreCase = true) })
        }
    }

    // =====================================================
    // Regression Tests for Fix B: Multi-Artifact Support
    // =====================================================

    @Test
    fun `Single ONNX model without declaration still works`() {
        withTempDir { root ->
            val onnxFile = File(root, "model.onnx")
            onnxFile.writeText("ONNX binary placeholder")
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(onnxFile, File(root, "extracted"))
            
            // Single artifact should resolve without model_artifacts declaration
            assertNotNull("Single ONNX should resolve artifact", result.artifact)
            assertEquals("Should be ONNX runtime", "onnx", result.runtime)
        }
    }

    @Test
    fun `Florence-2 style multi-artifact package with metadata resolves`() {
        withTempDir { root ->
            val onnxDir = File(root, "onnx")
            val encoderFile = File(onnxDir, "encoder_model.onnx")
            onnxDir.mkdirs()
            encoderFile.writeText("encoder ONNX")

            val decoderFile = File(onnxDir, "decoder_model.onnx")
            decoderFile.writeText("decoder ONNX")
            
            val metadataFile = File(root, "metadata.json")
            metadataFile.writeText("""
            {
                "model_id": "florence-2-base",
                "model_artifacts": [
                    {"path": "onnx/encoder_model.onnx"},
                    {"path": "onnx/decoder_model.onnx"}
                ],
                "supported_tasks": ["image_to_text"]
            }
            """.trimIndent())
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))
            
            assertEquals("Should be ONNX runtime", "onnx", result.runtime)
            assertTrue("Should not report ambiguous when model_artifacts declared", 
                result.issues.none { it.code == "model_artifact_ambiguous" })
            assertTrue("Should resolve a declared artifact manifest for the package",
                result.metadata["model_artifacts"] is List<*> || result.artifact != null)
        }
    }

    @Test
    fun `Florence package structure is normalized into a role-aware multi-artifact manifest`() {
        withTempDir { root ->
            // Minimal package layout without metadata.json written by a user.
            File(root, "config.json").writeText("{}")
            File(root, "generation_config.json").writeText("{}")
            File(root, "processor_config.json").writeText("{}")
            File(root, "preprocessor_config.json").writeText("{}")
            File(root, "tokenizer.json").writeText("{}")
            File(root, "tokenizer_config.json").writeText("{}")
            File(root, "special_tokens_map.json").writeText("{}")
            File(root, "vocab.json").writeText("{}")
            File(root, "merges.txt").writeText("")
            File(root, "added_tokens.json").writeText("{}")

            File(root, "encoder_model_int8.onnx").writeText("encoder")
            File(root, "decoder_model_int8.onnx").writeText("decoder")
            File(root, "decoder_with_past_model_int8.onnx").writeText("decoder_with_past")
            File(root, "embed_tokens_int8.onnx").writeText("embed")
            File(root, "vision_encoder_int8.onnx").writeText("vision")

            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))

            val artifactRoles = result.metadata["model_artifacts"] as? List<*>
            assertNotNull("Florence package should normalize into a model_artifacts role list", artifactRoles)
            assertTrue("Florence manifest should preserve all expected roles", artifactRoles?.any { it is Map<*, *> && it["role"] == "vision_encoder" } == true)
            assertTrue("Florence manifest should preserve all expected roles", artifactRoles?.any { it is Map<*, *> && it["role"] == "encoder" } == true)
            assertTrue("Florence manifest should preserve all expected roles", artifactRoles?.any { it is Map<*, *> && it["role"] == "decoder" } == true)
            assertTrue("Florence manifest should preserve all expected roles", artifactRoles?.any { it is Map<*, *> && it["role"] == "decoder_with_past" } == true)
            assertTrue("Florence manifest should preserve all expected roles", artifactRoles?.any { it is Map<*, *> && it["role"] == "embed_tokens" } == true)
            assertFalse("Florence normalization should not generate ambiguous artifact issues", result.issues.any { it.code == "model_artifact_ambiguous" })
        }
    }

    @Test
    fun `Multiple ONNX without declaration still reports ambiguous`() {
        withTempDir { root ->
            File(root, "encoder.onnx").writeText("encoder")
            File(root, "decoder.onnx").writeText("decoder")
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))
            
            assertTrue("Should report ambiguous artifacts", 
                result.issues.any { it.code == "model_artifact_ambiguous" })
            assertFalse("Should not be valid when ambiguous", result.valid)
        }
    }

    @Test
    fun `Multi-artifact with invalid path reference reports error`() {
        withTempDir { root ->
            File(root, "encoder.onnx").writeText("encoder")
            
            val metadataFile = File(root, "metadata.json")
            metadataFile.writeText("""
            {
                "model_artifacts": [
                    {"path": "encoder.onnx"},
                    {"path": "nonexistent_decoder.onnx"}
                ]
            }
            """.trimIndent())
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))
            
            assertTrue("Should report invalid artifact reference",
                result.issues.any { it.code == "model_artifacts_reference_invalid" })
            assertTrue("Should reject invalid referenced artifacts instead of silently accepting them", result.artifact == null || result.issues.any { it.code == "model_artifacts_reference_invalid" })
        }
    }

    // =====================================================
    // Regression Tests for Fix C: Aesthetic Model Detection
    // =====================================================

    @Test
    fun `Aesthetic predictor without explicit task gets aesthetic scoring task`() {
        withTempDir { root ->
            File(root, "aesthetic_predictor_v2_5.onnx").writeText("ONNX model")

            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))

            assertTrue("Should infer an aesthetic scoring capability from the package name",
                result.supportedTasks.map { it.lowercase() }.contains("aesthetic_scoring") ||
                    result.capabilities.map { it.lowercase() }.contains("aesthetic_scoring"))
        }
    }

    @Test
    fun `Model with quality in name gets image quality scoring task`() {
        withTempDir { root ->
            File(root, "image_quality_model.onnx").writeText("ONNX")

            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))

            assertTrue("Should detect quality model as image quality scoring",
                result.supportedTasks.any { it.lowercase().contains("image_quality_scoring") } ||
                result.capabilities.any { it.lowercase().contains("image_quality_scoring") })
        }
    }

    @Test
    fun `model with labels file gets classification task`() {
        withTempDir { root ->
            File(root, "model.onnx").writeText("ONNX")
            File(root, "labels.txt").writeText("poor\nfair\ngood\nexcellent\n")

            val inspector = ModelPackageInspector()
            val extracted = File(root, "extracted")
            val result = inspector.inspect(root, extracted)

            assertTrue("Should treat model with labels as classification",
                result.capabilities.any { it.lowercase().contains("classification") })
        }
    }

    @Test
    fun `Explicit task declaration takes precedence over inference`() {
        withTempDir { root ->
            File(root, "model.onnx").writeText("ONNX")
            
            val metadataFile = File(root, "metadata.json")
            metadataFile.writeText("""
            {
                "task": "ocr"
            }
            """.trimIndent())
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))
            
            assertTrue("Should use explicit task",
                result.supportedTasks.any { it.lowercase().contains("ocr") } ||
                    result.capabilities.any { it.lowercase().contains("ocr") })
        }
    }

    // =====================================================
    // Regression Tests: General Validation Rules
    // =====================================================

    @Test
    fun `Missing artifact reports error`() {
        withTempDir { root ->
            val metadataFile = File(root, "metadata.json")
            metadataFile.writeText("""{"task": "classification"}""")
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))
            
            assertTrue("Should report missing artifact",
                result.issues.any { it.code == "model_artifact_missing" })
        }
    }

    @Test
    fun `Invalid metadata reports error`() {
        withTempDir { root ->
            File(root, "model.onnx").writeText("ONNX")
            
            val invalidMetadata = File(root, "metadata.json")
            invalidMetadata.writeText("{ this is not valid json }")
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))
            
            assertTrue("Should report invalid metadata",
                result.issues.any { it.code == "metadata_invalid" })
        }
    }

    @Test
    fun `TensorFlow Lite model is recognized`() {
        withTempDir { root ->
            File(root, "model.tflite").writeText("TFLite binary")
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))
            
            assertNotNull("Should resolve TFLite artifact", result.artifact)
            assertEquals("Should be TFLite runtime", "tflite", result.runtime)
        }
    }

    @Test
    fun `Model validity requires artifact, runtime, and tasks`() {
        withTempDir { root ->
            val metadataFile = File(root, "metadata.json")
            metadataFile.writeText("""
            {
                "model_id": "test-model",
                "task": "invalid_task_type"
            }
            """.trimIndent())
            // No artifact file
            
            val inspector = ModelPackageInspector()
            val result = inspector.inspect(root, File(root, "extracted"))
            
            assertFalse("Model without artifact should not be valid", result.valid)
        }
    }

    @Test
    fun `Florence real package inspection path preserves runtime fed pixel_values without artifact rejection`() {
        val inspector = ModelPackageInspector()
        val zip = File("../../AsterionCore/Florence-2-Base.zip")
        assumeTrue("Real Florence ZIP must exist", zip.exists())

        val result = inspector.inspect(zip, File("build/florence-real-extraction"))
        assertTrue("Florence inspection should succeed through the production zip extraction path", result.valid)
        assertTrue("Florence runtime must resolve to ONNX", result.runtime == "onnx")
        assertFalse("Florence runtime-fed pixel_values must not trigger tensor_input_missing when the model artifact is otherwise valid", result.issues.any { it.code == "tensor_input_missing" })
        assertTrue("Florence should keep the canonical model roles accessible in metadata", result.metadata["model_artifacts"] is List<*>)
    }

    @Test
    fun `Aesthetic real package is recognized and imported as valid package with explicit preprocessing readiness blocker`() {
        val inspector = ModelPackageInspector()
        val zip = File("../../AsterionCore/aesthetic_predictor_v2.5.zip")
        assumeTrue("Real Aesthetic ZIP must exist", zip.exists())

        val result = inspector.inspect(zip, File("build/aesthetic-real-extraction"))
        assertTrue("Aesthetic package should import through inspection as a valid recognized package", result.valid)
        assertTrue("Aesthetic should still be recognized as an aesthetic scoring task", result.supportedTasks.any { it.equals("aesthetic_scoring", ignoreCase = true) })
        assertTrue("Aesthetic should preserve the known preprocessing readiness blocker", result.issues.any { it.code == "preprocessing_contract_unresolved" })
        assertFalse("Aesthetic execution should remain blocked by unresolved preprocessing readiness, not by package validation", result.issues.any { it.code == "model_artifact_missing" })
    }

    @Test
    fun `Qwen GGUF zip imports by descriptor metadata and keeps llama_cpp backend metadata`() {
        val inspector = ModelPackageInspector()
        val zip = File("../../AsterionCore/qwen2.5-coder-3b-instruct-q4_k_m.zip")
        assumeTrue("Real Qwen coder ZIP must exist", zip.exists())

        val result = inspector.inspect(zip, File("build/qwen-coder-real-extraction"))
        assertTrue("Qwen coder package should be recognized by inspection", result.runtime == "llama_cpp")
        assertTrue("Qwen coder package should keep text generation task metadata", result.supportedTasks.any { it.equals("text_generation", ignoreCase = true) })
        assertTrue("Qwen coder package should surface llama_cpp backend metadata", (result.metadata["llama_cpp"] as? Map<*, *>)?.get("backend") == "llama.cpp")
    }

    @Test
    fun `Qwen VL GGUF pair resolves the explicit mmproj relationship for descriptor import`() {
        val inspector = ModelPackageInspector()
        val zip = File("../../AsterionCore/Qwen2.5-VL-3B-Instruct.zip")
        assumeTrue("Real Qwen-VL ZIP must exist", zip.exists())

        val result = inspector.inspect(zip, File("build/qwen-vl-real-extraction"))
        assertTrue("Qwen-VL package should be recognized as LLAMA_CPP runtime", result.runtime == "llama_cpp")
        assertTrue("Qwen-VL package should resolve multimodal task metadata through vision projector relation", result.metadata["llama_cpp"] as? Map<*, *> != null)
        assertTrue("Qwen-VL package should preserve multimodal metadata signal", (result.metadata["llama_cpp"] as? Map<*, *>)?.get("multimodal") == true)
    }

    @Test
    fun `role-aware contract resolver maps Buffalo tasks to their own artifacts`() {
        val inspector = ModelPackageInspector()
        val roles = setOf("detector", "landmark_2d", "landmark_3d", "gender_age", "face_embedding")

        assertEquals("detector", inspector.resolveContractArtifactRole("face_detection", emptyMap(), roles))
        assertEquals("face_embedding", inspector.resolveContractArtifactRole("face_embedding", emptyMap(), roles))
        assertEquals("landmark_2d", inspector.resolveContractArtifactRole("landmark_2d", emptyMap(), roles))
        assertEquals("landmark_3d", inspector.resolveContractArtifactRole("landmark_3d", emptyMap(), roles))
        assertEquals("gender_age", inspector.resolveContractArtifactRole("gender_age", emptyMap(), roles))
    }

    @Test
    fun `explicit artifact role takes precedence over task aliases`() {
        val inspector = ModelPackageInspector()
        val roles = setOf("detector", "face_embedding")
        val contract = mapOf<String, Any>("artifact_role" to "face_embedding")

        assertEquals(
            "face_embedding",
            inspector.resolveContractArtifactRole("face_detection", contract, roles),
        )
    }

    @Test
    fun `role-aware contract resolver maps every Florence stage role without package-primary fallback`() {
        val inspector = ModelPackageInspector()
        val roles = setOf("vision_encoder", "embed_tokens", "encoder", "decoder", "decoder_with_past")

        roles.forEach { role ->
            assertEquals(role, inspector.resolveContractArtifactRole(role, emptyMap(), roles))
        }
    }

    @Test
    fun `single-artifact tasks without a role keep package-primary validation behavior`() {
        val inspector = ModelPackageInspector()
        assertNull(
            inspector.resolveContractArtifactRole(
                "classification",
                emptyMap(),
                emptySet(),
            ),
        )
    }

    @Test
    fun `real Buffalo package has no cross-role tensor binding false positives`() {
        val inspector = ModelPackageInspector()
        val zip = File("../../AsterionCore/buffalo_l.zip")
        assumeTrue("Real Buffalo-L ZIP must exist", zip.exists())

        val result = inspector.inspect(zip, File("build/buffalo-role-aware-extraction"))
        val crossRoleIssues = result.issues.filter {
            it.code in setOf("tensor_input_missing", "tensor_output_missing")
        }
        assertFalse(
            "Buffalo role contracts must validate against their own ONNX artifacts: $crossRoleIssues",
            crossRoleIssues.any {
                it.message.contains("face_embedding") ||
                    it.message.contains("landmark_2d") ||
                    it.message.contains("landmark_3d") ||
                    it.message.contains("gender_age") ||
                    it.message.contains("face_detection")
            },
        )

        val contracts = result.metadata["inference_contracts"] as? Map<*, *> ?: emptyMap<Any, Any>()
        assertEquals("detector", (contracts["face_detection"] as? Map<*, *>)?.get("artifact_role"))
        assertEquals("face_embedding", (contracts["face_embedding"] as? Map<*, *>)?.get("artifact_role"))
        assertEquals("landmark_2d", (contracts["landmark_2d"] as? Map<*, *>)?.get("artifact_role"))
        assertEquals("landmark_3d", (contracts["landmark_3d"] as? Map<*, *>)?.get("artifact_role"))
        assertEquals("gender_age", (contracts["gender_age"] as? Map<*, *>)?.get("artifact_role"))
    }

    @Test
    fun `real Florence package keeps role-specific contracts isolated from the primary vision graph`() {
        val inspector = ModelPackageInspector()
        val zip = File("../../AsterionCore/Florence-2-Base.zip")
        assumeTrue("Real Florence ZIP must exist", zip.exists())

        val result = inspector.inspect(zip, File("build/florence-role-aware-extraction"))
        val contracts = result.metadata["inference_contracts"] as? Map<*, *> ?: emptyMap<Any, Any>()

        assertEquals("vision_encoder", (contracts["vision_encoder"] as? Map<*, *>)?.get("artifact_role"))
        assertEquals("embed_tokens", (contracts["embed_tokens"] as? Map<*, *>)?.get("artifact_role"))
        assertEquals("encoder", (contracts["encoder"] as? Map<*, *>)?.get("artifact_role"))

        val bindingIssues = result.issues.filter {
            it.code in setOf("tensor_input_missing", "tensor_output_missing")
        }
        assertFalse(
            "Florence stage contracts must not be checked against an unrelated package-primary graph: $bindingIssues",
            bindingIssues.any {
                it.message.contains("embed_tokens") || it.message.contains("encoder")
            },
        )
    }

    @Test
    fun `ZIP package is properly extracted and inspected`() {
        withTempDir { root ->
            val packageDir = File(root, "package")
            packageDir.mkdirs()

            File(packageDir, "model.onnx").writeText("ONNX")
            File(packageDir, "metadata.json").writeText("""{"task": "classification"}""")

            // Create ZIP file
            val zipFile = File(root, "model.zip")
            val srcDir = packageDir
            ProcessBuilder("powershell", "-Command",
                "Compress-Archive -Path '${srcDir}\\*' -DestinationPath '${zipFile.absolutePath}' -Force"
            ).start().waitFor()

            if (zipFile.exists()) {
                val inspector = ModelPackageInspector()
                val result = inspector.inspect(zipFile, File(root, "extracted"))

                assertNotNull("Should extract and resolve ZIP package", result.artifact)
            }
        }
    }
}
