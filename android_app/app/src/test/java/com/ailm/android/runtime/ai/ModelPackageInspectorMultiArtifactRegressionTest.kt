package com.ailm.android.runtime.ai

import java.io.File
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelPackageInspectorMultiArtifactRegressionTest {
    @Test
    fun `role aware tensor validation follows each Buffalo artifact instead of the package primary`() {
        val root = createTempDirectory("asterion-buffalo-role-aware-").toFile()
        try {
            writeBuffaloFixture(root)
            val inspectedArtifacts = mutableListOf<String>()
            val inspector = ModelPackageInspector { artifact, runtime ->
                assertEquals(AiRuntimeType.ONNX.raw, runtime)
                inspectedArtifacts += artifact.name
                bindingsFor(artifact.name)
            }

            val inspection = inspector.inspect(root, File(root, "extracted"))

            assertEquals("det_10g.onnx", inspection.artifact?.name)
            val paths = inspection.metadata["artifact_paths_by_role"] as Map<*, *>
            assertEquals("det_10g.onnx", File(paths["detector"].toString()).name)
            assertEquals("w600k_r50.onnx", File(paths["face_embedding"].toString()).name)
            assertEquals("2d106det.onnx", File(paths["landmark_2d"].toString()).name)
            assertEquals("1k3d68.onnx", File(paths["landmark_3d"].toString()).name)
            assertEquals("genderage.onnx", File(paths["gender_age"].toString()).name)

            assertTrue(inspectedArtifacts.contains("det_10g.onnx"))
            assertTrue(inspectedArtifacts.contains("w600k_r50.onnx"))
            assertTrue(inspectedArtifacts.contains("2d106det.onnx"))
            assertTrue(inspectedArtifacts.contains("1k3d68.onnx"))
            assertTrue(inspectedArtifacts.contains("genderage.onnx"))

            val roleTasks = setOf("face_embedding", "landmark_2d", "landmark_3d", "gender_age")
            val falseCrossArtifactIssues = inspection.issues.filter { issue ->
                issue.code in setOf("tensor_input_missing", "tensor_output_missing") &&
                    roleTasks.any { task -> issue.message.startsWith(task) }
            }
            assertTrue(
                "Role-specific contracts must be validated against their owning artifacts: $falseCrossArtifactIssues",
                falseCrossArtifactIssues.isEmpty(),
            )
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun `role aware validation still rejects a genuinely invalid role specific tensor contract`() {
        val root = createTempDirectory("asterion-buffalo-invalid-role-").toFile()
        try {
            writeBuffaloFixture(root)
            val inspector = ModelPackageInspector { artifact, runtime ->
                assertEquals(AiRuntimeType.ONNX.raw, runtime)
                if (artifact.name == "w600k_r50.onnx") {
                    bindingsFor(artifact.name).copy(
                        outputs = listOf(tensor("wrong_embedding_output", 0, listOf(1, 512))),
                    )
                } else {
                    bindingsFor(artifact.name)
                }
            }

            val inspection = inspector.inspect(root, File(root, "extracted"))

            assertTrue(
                "A wrong role-specific output must be rejected. issues=${inspection.issues}",
                inspection.issues.any { issue ->
                    issue.code == "tensor_output_missing" &&
                        issue.message.startsWith("face_embedding") &&
                        issue.message.contains("'683'")
                },
            )
            assertFalse(
                inspection.issues.any { issue ->
                    issue.code == "tensor_output_missing" &&
                        issue.message.startsWith("landmark_2d")
                },
            )
            assertFalse("A missing declared output is blocking", inspection.valid)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun `single artifact tensor validation behavior remains unchanged`() {
        val root = createTempDirectory("asterion-single-artifact-").toFile()
        try {
            File(root, "model.onnx").writeText("fixture")
            File(root, "metadata.json").writeText(
                """
                {
                  "task": "classification",
                  "inference_contracts": {
                    "classification": {
                      "tokenizer": {"type": "none"},
                      "image_preprocessing": {
                        "enabled": true,
                        "width": 8,
                        "height": 8,
                        "channels": 3,
                        "color_space": "rgb",
                        "resize_mode": "stretch",
                        "scale": 1.0,
                        "mean": [0.0, 0.0, 0.0],
                        "std": [1.0, 1.0, 1.0]
                      },
                      "inputs": [
                        {
                          "name": "input",
                          "source": "image",
                          "data_type": "float32",
                          "layout": "nchw",
                          "shape": [1, 3, 8, 8]
                        }
                      ],
                      "outputs": [
                        {
                          "name": "output",
                          "index": 0,
                          "data_type": "float32",
                          "shape": [1, 1]
                        }
                      ],
                      "output_decoder": {
                        "type": "classification",
                        "output_name": "output",
                        "labels": ["ok"]
                      },
                      "confidence_scoring": {
                        "type": "softmax",
                        "threshold": 0.0
                      }
                    }
                  }
                }
                """.trimIndent(),
            )
            val inspector = ModelPackageInspector { artifact, runtime ->
                assertEquals("model.onnx", artifact.name)
                assertEquals(AiRuntimeType.ONNX.raw, runtime)
                ModelArtifactBindings(
                    inputs = listOf(tensor("input", 0, listOf(1, 3, 8, 8))),
                    outputs = listOf(tensor("output", 0, listOf(1, 1))),
                )
            }

            val inspection = inspector.inspect(root, File(root, "extracted"))

            assertNotNull(inspection.artifact)
            assertEquals("model.onnx", inspection.artifact?.name)
            assertEquals("onnx", inspection.runtime)
            assertTrue("classification" in inspection.supportedTasks)
            assertFalse(inspection.issues.any { it.code == "tensor_input_missing" })
            assertFalse(inspection.issues.any { it.code == "tensor_output_missing" })
        } finally {
            root.deleteRecursively()
        }
    }

    private fun writeBuffaloFixture(root: File) {
        listOf(
            "det_10g.onnx",
            "w600k_r50.onnx",
            "2d106det.onnx",
            "1k3d68.onnx",
            "genderage.onnx",
        ).forEach { name ->
            File(root, name).writeText("fixture:$name")
        }
    }

    private fun bindingsFor(name: String): ModelArtifactBindings = when (name) {
        "det_10g.onnx" -> ModelArtifactBindings(
            inputs = listOf(tensor("input.1", 0, listOf(1, 3, 640, 640))),
            outputs = listOf(
                tensor("score_8", 0, listOf(1, 2, 80, 80)),
                tensor("score_16", 1, listOf(1, 2, 40, 40)),
                tensor("score_32", 2, listOf(1, 2, 20, 20)),
                tensor("bbox_8", 3, listOf(1, 8, 80, 80)),
                tensor("bbox_16", 4, listOf(1, 8, 40, 40)),
                tensor("bbox_32", 5, listOf(1, 8, 20, 20)),
                tensor("kps_8", 6, listOf(1, 20, 80, 80)),
                tensor("kps_16", 7, listOf(1, 20, 40, 40)),
                tensor("kps_32", 8, listOf(1, 20, 20, 20)),
            ),
        )
        "w600k_r50.onnx" -> ModelArtifactBindings(
            inputs = listOf(tensor("input.1", 0, listOf(1, 3, 112, 112))),
            outputs = listOf(tensor("683", 0, listOf(1, 512))),
        )
        "2d106det.onnx" -> ModelArtifactBindings(
            inputs = listOf(tensor("data", 0, listOf(1, 3, 192, 192))),
            outputs = listOf(tensor("fc1", 0, listOf(1, 212))),
        )
        "1k3d68.onnx" -> ModelArtifactBindings(
            inputs = listOf(tensor("data", 0, listOf(1, 3, 192, 192))),
            outputs = listOf(tensor("fc1", 0, listOf(1, 3309))),
        )
        "genderage.onnx" -> ModelArtifactBindings(
            inputs = listOf(tensor("data", 0, listOf(1, 3, 96, 96))),
            outputs = listOf(tensor("fc1", 0, listOf(1, 3))),
        )
        else -> error("Unexpected fixture artifact: $name")
    }

    private fun tensor(name: String, index: Int, shape: List<Int>) =
        ModelArtifactTensor(name, index, "float32", shape)
}
