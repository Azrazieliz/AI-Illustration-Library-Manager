package com.ailm.android.runtime.ai

import android.graphics.Bitmap
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

internal data class ScrfdDetectorConfig(
    val featureStrides: IntArray = intArrayOf(8, 16, 32),
    val inputMean: Float = 127.5f,
    val inputStd: Float = 128.0f,
    val swapRb: Boolean = true,
    val detThreshold: Float = 0.5f,
    val nmsThreshold: Float = 0.4f,
    val keypointsEnabled: Boolean = true,
    val targetSize: Int = 640,
) {
    val featureLevels: Int = featureStrides.size
    val numAnchors: Int = 2
    val scoreThreshold: Float = detThreshold
}

internal data class ScrfdPreprocessedInput(
    val tensor: FloatArray,
    val width: Int,
    val height: Int,
    val originalWidth: Int,
    val originalHeight: Int,
    val detScale: Float,
)

internal data class ScrfdResizePlan(
    val resizedWidth: Int,
    val resizedHeight: Int,
    val padLeft: Int,
    val padTop: Int,
    val detScale: Float,
)

internal fun computeScrfdResizePlan(sourceWidth: Int, sourceHeight: Int, targetSize: Int): ScrfdResizePlan {
    require(sourceWidth > 0 && sourceHeight > 0 && targetSize > 0)
    val scale = targetSize.toFloat() / max(sourceWidth, sourceHeight).toFloat()
    val resizedWidth = max(1, (sourceWidth * scale).roundToInt())
    val resizedHeight = max(1, (sourceHeight * scale).roundToInt())
    return ScrfdResizePlan(
        resizedWidth = resizedWidth,
        resizedHeight = resizedHeight,
        padLeft = 0,
        padTop = 0,
        detScale = scale,
    )
}

internal fun normalizeScrfdRgbPixel(red: Float, green: Float, blue: Float, swapRb: Boolean = true): FloatArray {
    val channels = if (swapRb) floatArrayOf(blue, green, red) else floatArrayOf(red, green, blue)
    return channels.map { (it - 127.5f) / 128.0f }.toFloatArray()
}

internal fun scrfdHwcToNchw(hwc: FloatArray, width: Int, height: Int): FloatArray {
    require(hwc.size == width * height * 3)
    val planeSize = width * height
    return FloatArray(hwc.size).also { nchw ->
        for (pixel in 0 until planeSize) {
            nchw[pixel] = hwc[pixel * 3]
            nchw[planeSize + pixel] = hwc[pixel * 3 + 1]
            nchw[planeSize * 2 + pixel] = hwc[pixel * 3 + 2]
        }
    }
}

internal object ScrfdDetectorContract {
    fun validateOutputGroups(outputs: List<IntArray>): Boolean {
        if (outputs.size != 9) return false
        fun hasTerminalWidth(shape: IntArray, width: Int): Boolean =
            shape.size >= 2 && shape[1] in setOf(-1, width)
        return outputs.slice(0 until 3).all { hasTerminalWidth(it, 1) } &&
            outputs.slice(3 until 6).all { hasTerminalWidth(it, 4) } &&
            outputs.slice(6 until 9).all { hasTerminalWidth(it, 10) }
    }
}

internal data class ScrfdDetection(
    val x1: Float,
    val y1: Float,
    val x2: Float,
    val y2: Float,
    val score: Float,
    val keypoints: List<FloatArray>,
) {
    val width: Float get() = x2 - x1
    val height: Float get() = y2 - y1
}

internal class ScrfdDetector(
    private val config: ScrfdDetectorConfig = ScrfdDetectorConfig(),
) {
    fun preprocess(bitmap: Bitmap, targetSize: Int = config.targetSize): ScrfdPreprocessedInput {
        val sourceWidth = bitmap.width
        val sourceHeight = bitmap.height
        val plan = computeScrfdResizePlan(sourceWidth, sourceHeight, targetSize)
        val canvasWidth = plan.resizedWidth
        val canvasHeight = plan.resizedHeight
        val xOffset = plan.padLeft
        val yOffset = plan.padTop
        val stage = Bitmap.createScaledBitmap(bitmap, canvasWidth, canvasHeight, true)
        val pixels = IntArray(canvasWidth * canvasHeight)
        stage.getPixels(pixels, 0, canvasWidth, 0, 0, canvasWidth, canvasHeight)
        val tensor = FloatArray(targetSize * targetSize * 3)
        var index = 0
        for (y in 0 until targetSize) {
            for (x in 0 until targetSize) {
                val channelMap = if (x >= xOffset && x < xOffset + canvasWidth && y >= yOffset && y < yOffset + canvasHeight) {
                    val localX = x - xOffset
                    val localY = y - yOffset
                    val pixel = pixels[localY * canvasWidth + localX]
                    val r = ((pixel shr 16) and 0xff).toFloat()
                    val g = ((pixel shr 8) and 0xff).toFloat()
                    val b = (pixel and 0xff).toFloat()
                    floatArrayOf(r, g, b)
                } else {
                    floatArrayOf(0f, 0f, 0f)
                }
                val normalized = normalizeScrfdRgbPixel(channelMap[0], channelMap[1], channelMap[2], config.swapRb)
                tensor[index] = normalized[0]
                tensor[index + 1] = normalized[1]
                tensor[index + 2] = normalized[2]
                index += 3
            }
        }
        return ScrfdPreprocessedInput(
            tensor = tensor,
            width = targetSize,
            height = targetSize,
            originalWidth = sourceWidth,
            originalHeight = sourceHeight,
            detScale = plan.detScale,
        )
    }

    fun anchorCentersForStride(stride: Int, width: Int, height: Int, anchorCount: Int): List<FloatArray> {
        val results = mutableListOf<FloatArray>()
        val centersX = (0 until width).map { it * stride + stride / 2f }
        val centersY = (0 until height).map { it * stride + stride / 2f }
        for (y in centersY) {
            for (x in centersX) {
                repeat(anchorCount) { index ->
                    results += floatArrayOf(x + index * 0.5f, y + index * 0.5f)
                }
            }
        }
        return results
    }

    fun decodeDistanceBox(center: FloatArray, distances: FloatArray, stride: Float = 1f): FloatArray {
        require(center.size >= 2) { "Center must include x,y coordinates" }
        require(distances.size >= 4) { "BBox distances need left, top, right, bottom" }
        val cx = center[0]
        val cy = center[1]
        val scaled = distances.copyOf(4).map { it * stride }.toFloatArray()
        return floatArrayOf(
            cx - scaled[0],
            cy - scaled[1],
            cx + scaled[2],
            cy + scaled[3],
        )
    }

    fun decodeKeypoints(distances: FloatArray, centerX: Float, centerY: Float, stride: Float = 1f): List<FloatArray> {
        require(distances.size >= 10) { "SCRFD keypoints require 10 distance values for 5 points" }
        val points = mutableListOf<FloatArray>()
        for (i in 0 until 5) {
            val dx = distances[i * 2] * stride
            val dy = distances[i * 2 + 1] * stride
            points += floatArrayOf(centerX + dx, centerY + dy)
        }
        return points
    }

    fun decodeOutputs(outputs: List<List<Float>>, sourceWidth: Int, sourceHeight: Int): List<ScrfdDetection> {
        require(outputs.size == 9) { "SCRFD requires all 9 outputs, got ${outputs.size}" }
        val scoreOutputs = outputs.subList(0, 3)
        val bboxOutputs = outputs.subList(3, 6)
        val landmarkOutputs = outputs.subList(6, 9)
        val results = mutableListOf<ScrfdDetection>()
        for (level in 0 until 3) {
            val stride = config.featureStrides[level]
            val rows = sqrt((scoreOutputs[level].size / 2.0f).toDouble()).toInt().coerceAtLeast(1)
            val cols = max(1, (scoreOutputs[level].size / max(1, rows * 2)))
            val cellCount = rows * cols
            for (index in 0 until cellCount) {
                val scoreIndex = index * 2
                val score = scoreOutputs[level].getOrElse(scoreIndex) { 0f }
                if (score < config.detThreshold) continue
                val bboxIndex = index * 4
                val bbox = bboxOutputs[level].drop(bboxIndex).take(4).toFloatArray()
                if (bbox.size < 4) continue
                val centerX = (index % cols) * stride + stride / 2f
                val centerY = (index / cols) * stride + stride / 2f
                val box = decodeDistanceBox(floatArrayOf(centerX, centerY), bbox, stride.toFloat())
                val kpsIndex = index * 10
                val kps = landmarkOutputs[level].drop(kpsIndex).take(10).toFloatArray()
                val keypoints = if (kps.size >= 10) decodeKeypoints(kps, centerX, centerY, stride.toFloat()) else emptyList()
                val x1 = box[0].coerceIn(0f, sourceWidth.toFloat())
                val y1 = box[1].coerceIn(0f, sourceHeight.toFloat())
                val x2 = box[2].coerceIn(0f, sourceWidth.toFloat())
                val y2 = box[3].coerceIn(0f, sourceHeight.toFloat())
                results += ScrfdDetection(x1, y1, x2, y2, score, keypoints)
            }
        }
        return nms(results.filter { it.score >= config.detThreshold })
    }

    fun nms(candidates: List<ScrfdDetection>): List<ScrfdDetection> {
        val ordered = candidates.sortedByDescending { it.score }
        val kept = mutableListOf<ScrfdDetection>()
        for (candidate in ordered) {
            val overlaps = kept.any { boxIoU(candidate, it) > config.nmsThreshold }
            if (!overlaps) {
                kept += candidate
            }
        }
        return kept
    }

    private fun boxIoU(a: ScrfdDetection, b: ScrfdDetection): Float {
        val interLeft = max(a.x1, b.x1)
        val interTop = max(a.y1, b.y1)
        val interRight = min(a.x2, b.x2)
        val interBottom = min(a.y2, b.y2)
        val interWidth = max(0f, interRight - interLeft)
        val interHeight = max(0f, interBottom - interTop)
        val interArea = interWidth * interHeight
        val areaA = (a.x2 - a.x1) * (a.y2 - a.y1)
        val areaB = (b.x2 - b.x1) * (b.y2 - b.y1)
        val union = (areaA + areaB - interArea).coerceAtLeast(1e-6f)
        return interArea / union
    }
}
