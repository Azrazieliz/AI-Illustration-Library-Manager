package com.ailm.android.runtime.ai

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Matrix
import android.graphics.Paint
import kotlin.math.cos
import kotlin.math.sin

internal data class FaceBoundingBox(val x1: Float, val y1: Float, val x2: Float, val y2: Float)

internal data class FacePoint3d(val x: Float, val y: Float, val z: Float)

internal data class LandmarkAffineTransform(
    val scale: Float,
    val rotationRadians: Float,
    val translateX: Float,
    val translateY: Float,
) {
    fun map(point: FacePoint): FacePoint {
        val cosine = cos(rotationRadians) * scale
        val sine = sin(rotationRadians) * scale
        return FacePoint(cosine * point.x - sine * point.y + translateX, sine * point.x + cosine * point.y + translateY)
    }

    fun inverseMap(point: FacePoint): FacePoint {
        val dx = point.x - translateX
        val dy = point.y - translateY
        val cosine = cos(rotationRadians)
        val sine = sin(rotationRadians)
        return FacePoint((cosine * dx + sine * dy) / scale, (-sine * dx + cosine * dy) / scale)
    }

    fun inverseMap(point: FacePoint3d): FacePoint3d {
        val mapped = inverseMap(FacePoint(point.x, point.y))
        return FacePoint3d(mapped.x, mapped.y, point.z / scale)
    }
}

internal object InsightFaceLandmarkAlignment {
    const val OUTPUT_SIZE = 192
    const val COORDINATE_SCALE = OUTPUT_SIZE / 2f

    fun fromBoundingBox(bbox: FaceBoundingBox, outputSize: Int = OUTPUT_SIZE): LandmarkAffineTransform {
        require(outputSize > 0) { "Landmark crop output must be positive" }
        val width = bbox.x2 - bbox.x1
        val height = bbox.y2 - bbox.y1
        require(width > 0f && height > 0f) { "Face bounding box must have positive width and height" }
        val centerX = (bbox.x1 + bbox.x2) / 2f
        val centerY = (bbox.y1 + bbox.y2) / 2f
        val scale = outputSize / (maxOf(width, height) * 1.5f)
        return LandmarkAffineTransform(scale, 0f, outputSize / 2f - centerX * scale, outputSize / 2f - centerY * scale)
    }

    fun warp(bitmap: Bitmap, transform: LandmarkAffineTransform, outputSize: Int = OUTPUT_SIZE): Bitmap {
        require(outputSize > 0) { "Landmark crop output must be positive" }
        val output = Bitmap.createBitmap(outputSize, outputSize, Bitmap.Config.ARGB_8888)
        val matrix = Matrix().apply {
            val cosine = cos(transform.rotationRadians) * transform.scale
            val sine = sin(transform.rotationRadians) * transform.scale
            setValues(floatArrayOf(
                cosine, -sine, transform.translateX,
                sine, cosine, transform.translateY,
                0f, 0f, 1f,
            ))
        }
        Canvas(output).apply {
            drawColor(0)
            drawBitmap(bitmap, matrix, Paint(Paint.FILTER_BITMAP_FLAG))
        }
        return output
    }

    fun modelOutputToCropCoordinates(output: List<Float>): List<FacePoint> {
        require(output.size == 212) { "2D landmark output must contain exactly 212 values" }
        return output.chunked(2).map { pair ->
            FacePoint((pair[0] + 1f) * COORDINATE_SCALE, (pair[1] + 1f) * COORDINATE_SCALE)
        }
    }

    fun modelOutputToSourceCoordinates(output: List<Float>, transform: LandmarkAffineTransform): List<FacePoint> =
        modelOutputToCropCoordinates(output).map(transform::inverseMap)

    fun model3dOutputToSourceCoordinates(output: List<Float>, transform: LandmarkAffineTransform): List<FacePoint3d> {
        require(output.size == 3309) { "3D landmark output must contain exactly 3309 values" }
        val rows = output.chunked(3)
        require(rows.size == 1103) { "3D landmark output must reshape to 1103 rows" }
        return rows.takeLast(68).map { row ->
            transform.inverseMap(FacePoint3d((row[0] + 1f) * COORDINATE_SCALE, (row[1] + 1f) * COORDINATE_SCALE, row[2] * COORDINATE_SCALE))
        }
    }
}

internal data class GenderAgePrediction(
    val genderIndex: Int,
    val age: Int,
    val rawOutput: List<Float>,
)

internal fun decodeGenderAge(output: List<Float>): GenderAgePrediction {
    require(output.size == 3) { "Gender-age output must contain exactly 3 values" }
    val genderIndex = if (output[0] >= output[1]) 0 else 1
    return GenderAgePrediction(genderIndex, kotlin.math.round(output[2] * 100f).toInt(), output)
}

internal fun normalizeLandmarkChannel(value: Float, mean: Float, std: Float): Float = (value - mean) / std
