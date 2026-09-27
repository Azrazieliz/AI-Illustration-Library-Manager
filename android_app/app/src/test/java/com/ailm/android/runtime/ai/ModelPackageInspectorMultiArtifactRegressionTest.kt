package com.ailm.android.runtime.ai

import java.io.ByteArrayOutputStream
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
            val primaryBindings = ModelArtifactInspector.inspect(File(root, "det_10g.onnx"), AiRuntimeType.ONNX.raw)
            val embeddingBindings = ModelArtifactInspector.inspect(File(root, "w600k_r50.onnx"), AiRuntimeType.ONNX.raw)
            assertEquals(9, primaryBindings.outputs.size)
            assertEquals(listOf("683"), embeddingBindings.outputs.map { it.name })

            val inspection = ModelPackageInspector().inspect(root, File(root, "extracted"))
            assertFalse(
                "All deterministic ONNX fixtures must be inspectable: ${inspection.issues}",
                inspection.issues.any { it.code == "tensor_metadata_unreadable" },
            )

            assertEquals("det_10g.onnx", inspection.artifact?.name)
            val paths = inspection.metadata["artifact_paths_by_role"] as Map<*, *>
            assertEquals("det_10g.onnx", File(paths["detector"].toString()).name)
            assertEquals("w600k_r50.onnx", File(paths["face_embedding"].toString()).name)
            assertEquals("2d106det.onnx", File(paths["landmark_2d"].toString()).name)
            assertEquals("1k3d68.onnx", File(paths["landmark_3d"].toString()).name)
            assertEquals("genderage.onnx", File(paths["gender_age"].toString()).name)

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
            writeBuffaloFixture(root, faceEmbeddingOutput = "wrong_embedding_output")
            val embeddingBindings = ModelArtifactInspector.inspect(File(root, "w600k_r50.onnx"), AiRuntimeType.ONNX.raw)
            assertEquals(listOf("wrong_embedding_output"), embeddingBindings.outputs.map { it.name })

            val inspection = ModelPackageInspector().inspect(root, File(root, "extracted"))
            assertFalse(
                "The malformed role fixture must still have readable tensor metadata: ${inspection.issues}",
                inspection.issues.any { it.code == "tensor_metadata_unreadable" },
            )

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
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun `single artifact tensor validation behavior remains unchanged`() {
        val root = createTempDirectory("asterion-single-artifact-").toFile()
        try {
            MinimalOnnxFixture.writeIdentityModel(
                File(root, "model.onnx"),
                inputName = "input",
                outputNames = listOf("output"),
                shape = listOf(1, 3, 8, 8),
            )
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
                          "shape": [1, 3, 8, 8]
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

            val inspection = ModelPackageInspector().inspect(root, File(root, "extracted"))

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

    private fun writeBuffaloFixture(root: File, faceEmbeddingOutput: String = "683") {
        MinimalOnnxFixture.writeIdentityModel(
            File(root, "det_10g.onnx"),
            inputName = "input.1",
            outputNames = List(9) { index -> "det_output_$index" },
            shape = listOf(1, 3, 640, 640),
        )
        MinimalOnnxFixture.writeIdentityModel(
            File(root, "w600k_r50.onnx"),
            inputName = "input.1",
            outputNames = listOf(faceEmbeddingOutput),
            shape = listOf(1, 3, 112, 112),
        )
        MinimalOnnxFixture.writeIdentityModel(
            File(root, "2d106det.onnx"),
            inputName = "data",
            outputNames = listOf("fc1"),
            shape = listOf(1, 3, 192, 192),
        )
        MinimalOnnxFixture.writeIdentityModel(
            File(root, "1k3d68.onnx"),
            inputName = "data",
            outputNames = listOf("fc1"),
            shape = listOf(1, 3, 192, 192),
        )
        MinimalOnnxFixture.writeIdentityModel(
            File(root, "genderage.onnx"),
            inputName = "data",
            outputNames = listOf("fc1"),
            shape = listOf(1, 3, 96, 96),
        )
    }
}

private object MinimalOnnxFixture {
    fun writeIdentityModel(
        file: File,
        inputName: String,
        outputNames: List<String>,
        shape: List<Int>,
    ) {
        require(outputNames.isNotEmpty())
        file.parentFile?.mkdirs()
        file.writeBytes(model(inputName, outputNames, shape))
    }

    private fun model(inputName: String, outputNames: List<String>, shape: List<Int>): ByteArray {
        val graph = proto {
            outputNames.forEach { outputName ->
                message(1, node(inputName, outputName))
            }
            string(2, "asterion_test_graph")
            message(11, valueInfo(inputName, shape))
            outputNames.forEach { outputName ->
                message(12, valueInfo(outputName, shape))
            }
        }
        val opset = proto {
            string(1, "")
            varint(2, 13)
        }
        return proto {
            varint(1, 8)
            string(2, "asterion-core-regression")
            message(7, graph)
            message(8, opset)
        }
    }

    private fun node(inputName: String, outputName: String): ByteArray = proto {
        string(1, inputName)
        string(2, outputName)
        string(4, "Identity")
    }

    private fun valueInfo(name: String, shape: List<Int>): ByteArray = proto {
        string(1, name)
        message(
            2,
            proto {
                message(
                    1,
                    proto {
                        varint(1, 1)
                        message(
                            2,
                            proto {
                                shape.forEach { dimension ->
                                    message(
                                        1,
                                        proto {
                                            varint(1, dimension.toLong())
                                        },
                                    )
                                }
                            },
                        )
                    },
                )
            },
        )
    }

    private fun proto(block: ProtoWriter.() -> Unit): ByteArray =
        ProtoWriter().apply(block).toByteArray()

    private class ProtoWriter {
        private val output = ByteArrayOutputStream()

        fun varint(field: Int, value: Long) {
            tag(field, 0)
            rawVarint(value)
        }

        fun string(field: Int, value: String) {
            bytes(field, value.toByteArray(Charsets.UTF_8))
        }

        fun message(field: Int, value: ByteArray) {
            bytes(field, value)
        }

        private fun bytes(field: Int, value: ByteArray) {
            tag(field, 2)
            rawVarint(value.size.toLong())
            output.write(value)
        }

        private fun tag(field: Int, wireType: Int) {
            rawVarint(((field shl 3) or wireType).toLong())
        }

        private fun rawVarint(raw: Long) {
            var value = raw
            do {
                var next = (value and 0x7f).toInt()
                value = value ushr 7
                if (value != 0L) {
                    next = next or 0x80
                }
                output.write(next)
            } while (value != 0L)
        }

        fun toByteArray(): ByteArray = output.toByteArray()
    }
}
