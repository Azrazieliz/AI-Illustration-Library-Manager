package com.ailm.android.runtime.ai

import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import ai.onnxruntime.TensorInfo
import java.io.File
import org.tensorflow.lite.Interpreter

internal data class ModelArtifactTensor(
    val name: String,
    val index: Int,
    val dataType: String,
    val shape: List<Int>,
)

internal data class ModelArtifactBindings(
    val inputs: List<ModelArtifactTensor>,
    val outputs: List<ModelArtifactTensor>,
)

internal object ModelArtifactInspector {
    fun inspect(artifact: File, runtime: String): ModelArtifactBindings = when (runtime) {
        AiRuntimeType.ONNX.raw -> inspectOnnx(artifact)
        AiRuntimeType.TFLITE.raw -> inspectTensorFlowLite(artifact)
        else -> error("Unsupported executable runtime '$runtime'")
    }

    private fun inspectOnnx(artifact: File): ModelArtifactBindings {
        val environment = OrtEnvironment.getEnvironment()
        OrtSession.SessionOptions().use { options ->
            environment.createSession(artifact.absolutePath, options).use { session ->
                return ModelArtifactBindings(
                    inputs = session.inputInfo.entries.mapIndexed { index, (name, node) ->
                        node.tensor(name, index)
                    },
                    outputs = session.outputInfo.entries.mapIndexed { index, (name, node) ->
                        node.tensor(name, index)
                    },
                )
            }
        }
    }

    private fun ai.onnxruntime.NodeInfo.tensor(name: String, index: Int): ModelArtifactTensor {
        val info = info as? TensorInfo ?: error("ONNX value '$name' is not a tensor")
        return ModelArtifactTensor(
            name = name,
            index = index,
            dataType = normalizeDataType(info.type.name),
            shape = info.shape.map { dimension -> dimension.coerceIn(-1L, Int.MAX_VALUE.toLong()).toInt() },
        )
    }

    private fun inspectTensorFlowLite(artifact: File): ModelArtifactBindings = Interpreter(artifact).use { interpreter ->
        ModelArtifactBindings(
            inputs = List(interpreter.inputTensorCount) { index ->
                interpreter.getInputTensor(index).let { tensor ->
                    ModelArtifactTensor(
                        name = tensor.name(),
                        index = index,
                        dataType = normalizeDataType(tensor.dataType().name),
                        shape = tensor.shape().toList(),
                    )
                }
            },
            outputs = List(interpreter.outputTensorCount) { index ->
                interpreter.getOutputTensor(index).let { tensor ->
                    ModelArtifactTensor(
                        name = tensor.name(),
                        index = index,
                        dataType = normalizeDataType(tensor.dataType().name),
                        shape = tensor.shape().toList(),
                    )
                }
            },
        )
    }

    private fun normalizeDataType(raw: String): String = when (raw.lowercase()) {
        "float", "float32" -> "float32"
        "int64" -> "int64"
        "int32" -> "int32"
        "uint8" -> "uint8"
        "int8" -> "int8"
        "float16" -> "float16"
        else -> raw.lowercase()
    }
}