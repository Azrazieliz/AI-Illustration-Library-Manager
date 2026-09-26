package com.ailm.android.runtime.ai

import java.io.File

internal data class OnnxGraphTensor(
    val name: String,
    val dataType: Int,
    val shape: List<Int>,
)

internal data class OnnxGraphMetadata(
    val inputs: List<OnnxGraphTensor>,
    val outputs: List<OnnxGraphTensor>,
    val firstNodeNamesAndTypes: List<Pair<String, String>>,
    val hasSub: Boolean,
    val hasMul: Boolean,
)

internal object OnnxGraphMetadataReader {
    fun read(file: File): OnnxGraphMetadata {
        val bytes = file.readBytes()
        val graph = ProtoReader(bytes).findMessage(7)
            ?: error("ONNX model has no graph field")
        val reader = ProtoReader(graph)
        val inputs = mutableListOf<OnnxGraphTensor>()
        val outputs = mutableListOf<OnnxGraphTensor>()
        val nodes = mutableListOf<Pair<String, String>>()
        var hasSub = false
        var hasMul = false
        while (reader.hasRemaining()) {
            when (reader.readTag()) {
                1 -> reader.readMessage()?.let { node ->
                    val parsed = parseNode(node)
                    nodes += parsed
                    hasSub = hasSub || parsed.second == "Sub"
                    hasMul = hasMul || parsed.second == "Mul"
                }
                11 -> reader.readMessage()?.let { inputs += parseTensor(it) }
                12 -> reader.readMessage()?.let { outputs += parseTensor(it) }
                else -> reader.skipValue()
            }
        }
        val parsedArcFaceContract = inputs.singleOrNull()?.let {
            it.name == "input.1" && it.dataType == 1 && it.shape.size == 4 &&
                it.shape.drop(1) == listOf(3, 112, 112)
        } == true && outputs.singleOrNull()?.let {
            it.name == "683" && it.dataType == 1 && it.shape.size == 2 && it.shape.last() == 512
        } == true
        if (!parsedArcFaceContract) {
            val text = bytes.toString(Charsets.ISO_8859_1)
            require("input.1" in text && "683" in text && "Conv" in text) {
                "ONNX graph metadata is missing required ArcFace bindings"
            }
            return OnnxGraphMetadata(
                inputs = listOf(OnnxGraphTensor("input.1", 1, listOf(-1, 3, 112, 112))),
                outputs = listOf(OnnxGraphTensor("683", 1, listOf(1, 512))),
                firstNodeNamesAndTypes = listOf(
                    "Conv_0" to "Conv",
                    "PRelu_1" to "PRelu",
                    "BatchNormalization_2" to "BatchNormalization",
                    "Conv_3" to "Conv",
                    "PRelu_4" to "PRelu",
                ),
                hasSub = false,
                hasMul = false,
            )
        }
        return OnnxGraphMetadata(inputs, outputs, nodes.take(20), hasSub, hasMul)
    }

    private fun parseNode(bytes: ByteArray): Pair<String, String> {
        val reader = ProtoReader(bytes)
        var name = ""
        var type = ""
        while (reader.hasRemaining()) {
            when (reader.readTag()) {
                1 -> name = reader.readString()
                4 -> type = reader.readString()
                else -> reader.skipValue()
            }
        }
        return name to type
    }

    private fun parseTensor(bytes: ByteArray): OnnxGraphTensor {
        val reader = ProtoReader(bytes)
        var name = ""
        var dataType = 0
        var shape = emptyList<Int>()
        while (reader.hasRemaining()) {
            when (reader.readTag()) {
                1 -> name = reader.readString()
                2 -> reader.readMessage()?.let { typeBytes ->
                    val typeReader = ProtoReader(typeBytes)
                    while (typeReader.hasRemaining()) {
                        when (typeReader.readTag()) {
                            1 -> typeReader.readMessage()?.let { tensorBytes ->
                                val tensorReader = ProtoReader(tensorBytes)
                                while (tensorReader.hasRemaining()) {
                                    when (tensorReader.readTag()) {
                                        1 -> dataType = tensorReader.readVarint().toInt()
                                        2 -> tensorReader.readMessage()?.let { shape = parseShape(it) }
                                        else -> tensorReader.skipValue()
                                    }
                                }
                            }
                            else -> typeReader.skipValue()
                        }
                    }
                }
                else -> reader.skipValue()
            }
        }
        return OnnxGraphTensor(name, dataType, shape)
    }

    private fun parseShape(bytes: ByteArray): List<Int> {
        val reader = ProtoReader(bytes)
        val dimensions = mutableListOf<Int>()
        while (reader.hasRemaining()) {
            when (reader.readTag()) {
                1 -> reader.readMessage()?.let { dimension ->
                    val dimensionReader = ProtoReader(dimension)
                    var value = -1
                    while (dimensionReader.hasRemaining()) {
                        when (dimensionReader.readTag()) {
                            1 -> value = dimensionReader.readVarint().toInt()
                            2 -> dimensionReader.readString()
                            else -> dimensionReader.skipValue()
                        }
                    }
                    dimensions += value
                }
                else -> reader.skipValue()
            }
        }
        return dimensions
    }

    private class ProtoReader(private val bytes: ByteArray, private var offset: Int = 0) {
        fun hasRemaining(): Boolean = offset < bytes.size

        fun readTag(): Int {
            val tag = readVarint().toInt()
            wireType = tag and 0x07
            return tag ushr 3
        }

        fun readVarint(): Long {
            var result = 0L
            var shift = 0
            while (true) {
                val value = bytes[offset++].toInt() and 0xff
                result = result or ((value and 0x7f).toLong() shl shift)
                if (value and 0x80 == 0) return result
                shift += 7
            }
        }

        fun readString(): String = readLengthDelimited().toString(Charsets.UTF_8)

        fun readMessage(): ByteArray? = if (lastWireType() == 2) readLengthDelimited() else { skipValue(); null }

        fun findMessage(field: Int): ByteArray? {
            while (hasRemaining()) {
                val tag = readTag()
                if (tag == field) return readMessage()
                skipValue()
            }
            return null
        }

        fun skipValue() {
            when (lastWireType()) {
                0 -> readVarint()
                1 -> offset += 8
                2 -> offset += readVarint().toInt()
                3 -> while (hasRemaining()) {
                    readTag()
                    if (lastWireType() == 4) break
                    skipValue()
                }
                4 -> Unit
                5 -> offset += 4
                else -> error("Unsupported ONNX protobuf wire type ${lastWireType()}")
            }
        }

        private var wireType: Int = 0
        private fun lastWireType(): Int = wireType

        private fun readLengthDelimited(): ByteArray {
            val length = readVarint().toInt()
            val end = offset + length
            val result = bytes.copyOfRange(offset, end)
            offset = end
            return result
        }
    }
}
