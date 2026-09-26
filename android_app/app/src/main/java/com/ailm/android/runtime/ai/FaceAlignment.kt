package com.ailm.android.runtime.ai

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Matrix
import android.graphics.Paint
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

internal data class FacePoint(val x: Float, val y: Float)

internal data class FaceSimilarityTransform(
    val scale: Float,
    val rotationRadians: Float,
    val translateX: Float,
    val translateY: Float,
) {
    fun map(point: FacePoint): FacePoint {
        val c = cos(rotationRadians) * scale
        val s = sin(rotationRadians) * scale
        return FacePoint(c * point.x - s * point.y + translateX, s * point.x + c * point.y + translateY)
    }

    fun inverseMap(point: FacePoint): FacePoint {
        val dx = point.x - translateX
        val dy = point.y - translateY
        val c = cos(rotationRadians)
        val s = sin(rotationRadians)
        return FacePoint((c * dx + s * dy) / scale, (-s * dx + c * dy) / scale)
    }
}

internal object ArcFaceAlignment {
    const val OUTPUT_SIZE = 112
    val TEMPLATE = listOf(
        FacePoint(38.2946f, 51.6963f),
        FacePoint(73.5318f, 51.5014f),
        FacePoint(56.0252f, 71.7366f),
        FacePoint(41.5493f, 92.3655f),
        FacePoint(70.7299f, 92.2041f),
    )

    fun estimateSimilarityTransform(source: List<FacePoint>, destination: List<FacePoint> = TEMPLATE): FaceSimilarityTransform {
        require(source.size == 5 && destination.size == 5) { "ArcFace alignment requires five landmarks" }
        val sourceCenter = centroid(source)
        val destinationCenter = centroid(destination)
        var sourceEnergy = 0f
        var crossA = 0f
        var crossB = 0f
        source.indices.forEach { index ->
            val sx = source[index].x - sourceCenter.x
            val sy = source[index].y - sourceCenter.y
            val dx = destination[index].x - destinationCenter.x
            val dy = destination[index].y - destinationCenter.y
            sourceEnergy += sx * sx + sy * sy
            crossA += sx * dx + sy * dy
            crossB += sx * dy - sy * dx
        }
        require(sourceEnergy > 0f) { "ArcFace source landmarks are degenerate" }
        val scale = sqrt(crossA * crossA + crossB * crossB) / sourceEnergy
        val rotation = atan2(crossB, crossA)
        val transformedCenter = FaceSimilarityTransform(scale, rotation, 0f, 0f).map(sourceCenter)
        return FaceSimilarityTransform(
            scale = scale,
            rotationRadians = rotation,
            translateX = destinationCenter.x - transformedCenter.x,
            translateY = destinationCenter.y - transformedCenter.y,
        )
    }

    fun warp(bitmap: Bitmap, source: List<FacePoint>, outputSize: Int = OUTPUT_SIZE): Bitmap {
        require(outputSize == OUTPUT_SIZE) { "ArcFace alignment output must be 112x112" }
        val transform = estimateSimilarityTransform(source)
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

    private fun centroid(points: List<FacePoint>): FacePoint = FacePoint(
        points.sumOf { it.x.toDouble() }.toFloat() / points.size,
        points.sumOf { it.y.toDouble() }.toFloat() / points.size,
    )
}

internal fun normalizeArcFaceChannel(value: Float, mean: Float = 127.5f, std: Float = 127.5f): Float =
    (value - mean) / std

internal fun normalizeL2(values: List<Float>): List<Float> {
    val norm = sqrt(values.sumOf { it.toDouble() * it.toDouble() }).toFloat()
    if (norm == 0f) return List(values.size) { 0f }
    return values.map { it / norm }
}
