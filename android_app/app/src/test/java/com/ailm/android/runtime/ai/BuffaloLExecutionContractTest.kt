package com.ailm.android.runtime.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.File
import kotlin.math.abs
import kotlin.math.sqrt

class BuffaloLExecutionContractTest {
    private val packageDirectory = TestPackageFixtureResolver.resolvePackageDirectory(
        packageName = "buffalo_l",
        zipName = "buffalo_l.zip",
    )

    @Test
    fun `real package resolves coordinated buffalo_l roles`() {
        val inspection = inspectPackage()
        val roles = (inspection.metadata["model_artifacts"] as? List<*>)
            .orEmpty()
            .mapNotNull { (it as? Map<*, *>)?.get("role")?.toString() }
        assertTrue(roles.contains("detector"))
        assertTrue(roles.contains("landmark_2d"))
        assertTrue(roles.contains("face_embedding"))
        assertTrue(roles.contains("gender_age"))
        assertTrue(roles.contains("landmark_3d"))
        assertTrue(inspection.supportedTasks.contains("face_feature_extraction"))
        assertFalse(inspection.issues.any { it.code == "model_artifact_ambiguous" })
    }

    @Test
    fun `buffalo_l package is partly ready while other features remain unresolved`() {
        val inspection = inspectPackage()
        val capabilities = inspection.metadata["buffalo_l_capabilities"] as? Map<*, *> ?: emptyMap<Any, Any>()
        val faceDetection = capabilities["face_detection"] as? Map<*, *> ?: emptyMap<Any, Any>()
        assertFalse(inspection.valid)
        assertTrue(inspection.metadata.containsKey("buffalo_l_capabilities"))
        assertEquals(true, faceDetection["ready"])
        assertEquals(true, (capabilities["face_embedding"] as? Map<*, *>)?.get("ready"))
        assertEquals(true, (capabilities["landmark_2d"] as? Map<*, *>)?.get("ready"))
        assertEquals(true, (capabilities["landmark_3d"] as? Map<*, *>)?.get("ready"))
        assertEquals(true, (capabilities["gender_age"] as? Map<*, *>)?.get("ready"))
    }

    @Test
    fun `scrfd config matches official detector defaults`() {
        val config = ScrfdDetectorConfig()
        assertEquals(listOf(8, 16, 32), config.featureStrides.toList())
        assertEquals(3, config.featureLevels)
        assertEquals(2, config.numAnchors)
        assertEquals(0.5f, config.detThreshold, 1e-6f)
        assertEquals(0.4f, config.nmsThreshold, 1e-6f)
        assertEquals(127.5f, config.inputMean, 1e-6f)
        assertEquals(128.0f, config.inputStd, 1e-6f)
        assertEquals(640, config.targetSize)
        assertTrue(config.swapRb)
    }

    @Test
    fun `scrfd preprocessing preserves aspect ratio with zero padding`() {
        val plan = computeScrfdResizePlan(200, 100, 640)
        assertEquals(640, plan.resizedWidth)
        assertEquals(320, plan.resizedHeight)
        assertEquals(0, plan.padLeft)
        assertEquals(0, plan.padTop)
        assertEquals(3.2f, plan.detScale, 1e-6f)

        val normalized = normalizeScrfdRgbPixel(255f, 127.5f, 0f, swapRb = true)
        assertEquals(-127.5f / 128f, normalized[0], 1e-6f)
        assertEquals(0f, normalized[1], 1e-6f)
        assertEquals(127.5f / 128f, normalized[2], 1e-6f)

        val nchw = scrfdHwcToNchw(normalized, 1, 1)
        assertEquals(normalized.toList(), nchw.toList())
    }

    @Test
    fun `scrfd validation accepts official 9-output graph contract`() {
        val outputs = listOf(
            intArrayOf(1, 1, 8, 8),
            intArrayOf(1, 1, 4, 4),
            intArrayOf(1, 1, 2, 2),
            intArrayOf(1, 4, 8, 8),
            intArrayOf(1, 4, 4, 4),
            intArrayOf(1, 4, 2, 2),
            intArrayOf(1, 10, 8, 8),
            intArrayOf(1, 10, 4, 4),
            intArrayOf(1, 10, 2, 2),
        )
        assertTrue(ScrfdDetectorContract.validateOutputGroups(outputs))
    }

    @Test
    fun `scrfd anchor decode and bbox decode follow official distance math`() {
        val detector = ScrfdDetector()
        val centers = detector.anchorCentersForStride(8, 8, 8, 2)
        assertTrue(centers.size > 0)
        val center = centers.first()
        val distances = floatArrayOf(4f, 6f, 10f, 12f)
        val bbox = detector.decodeDistanceBox(center, distances)
        assertEquals(center[0] - 4f, bbox[0], 1e-4f)
        assertEquals(center[1] - 6f, bbox[1], 1e-4f)
        assertEquals(center[0] + 10f, bbox[2], 1e-4f)
        assertEquals(center[1] + 12f, bbox[3], 1e-4f)
    }

    @Test
    fun `scrfd kps decode returns 5 points from per-anchor distances`() {
        val detector = ScrfdDetector()
        val result = detector.decodeKeypoints(floatArrayOf(1f, 2f, 3f, 4f, 5f, 6f, 7f, 8f, 9f, 10f), 10f, 20f)
        assertEquals(5, result.size)
        assertEquals(10f + 1f, result[0][0], 1e-4f)
        assertEquals(20f + 2f, result[0][1], 1e-4f)
        assertEquals(10f + 3f, result[1][0], 1e-4f)
        assertEquals(20f + 4f, result[1][1], 1e-4f)
    }

    @Test
    fun `scrfd nms keeps dominant overlap below official threshold`() {
        val detector = ScrfdDetector()
        val boxes = listOf(
            ScrfdDetection(0f, 0f, 10f, 10f, 0.9f, emptyList()),
            ScrfdDetection(1f, 1f, 11f, 11f, 0.8f, emptyList()),
            ScrfdDetection(20f, 20f, 30f, 30f, 0.7f, emptyList()),
        )
        val kept = detector.nms(boxes)
        assertEquals(2, kept.size)
        assertEquals(0.9f, kept[0].score, 1e-6f)
    }

    @Test
    fun `buffalo_l detection artifact resolves to det_10g and uses canonical face_detection task`() {
        val inspection = inspectPackage()
        val roles = (inspection.metadata["model_artifacts"] as? List<*>)
            .orEmpty()
            .mapNotNull { (it as? Map<*, *>)?.get("role")?.toString() }
        assertTrue(roles.contains("detector"))
        assertTrue(roles.contains("landmark_2d"))
        assertTrue(roles.contains("landmark_3d"))
        assertTrue(roles.contains("gender_age"))
        assertTrue(roles.contains("face_embedding"))
        assertTrue(inspection.supportedTasks.contains("face_detection"))
        assertEquals("det_10g.onnx", inspection.artifact?.name)
    }

    @Test
    fun `face embedding role routes to w600k_r50`() {
        val inspection = inspectPackage()
        val paths = inspection.metadata["artifact_paths_by_role"] as Map<*, *>
        assertTrue(paths["face_embedding"].toString().endsWith("w600k_r50.onnx"))
        assertFalse(paths["face_embedding"].toString().endsWith("det_10g.onnx"))
    }

    @Test
    fun `2d landmark role routes to 2d106det`() {
        val inspection = inspectPackage()
        val paths = inspection.metadata["artifact_paths_by_role"] as Map<*, *>
        assertTrue(paths["landmark_2d"].toString().endsWith("2d106det.onnx"))
        assertFalse(paths["landmark_2d"].toString().endsWith("w600k_r50.onnx"))
    }

    @Test
    fun `3d landmark role routes to 1k3d68`() {
        val inspection = inspectPackage()
        val paths = inspection.metadata["artifact_paths_by_role"] as Map<*, *>
        assertTrue(paths["landmark_3d"].toString().endsWith("1k3d68.onnx"))
        assertFalse(paths["landmark_3d"].toString().endsWith("2d106det.onnx"))
    }

    @Test
    fun `real 2d landmark graph contract is data and fc1 with 212 dimensions`() {
        val inspection = inspectPackage()
        val contract = (inspection.metadata["inference_contracts"] as Map<*, *>) ["landmark_2d"] as Map<*, *>
        val input = (contract["inputs"] as List<*>) [0] as Map<*, *>
        val output = (contract["outputs"] as List<*>) [0] as Map<*, *>
        assertEquals("data", input["name"])
        assertEquals("float32", input["data_type"])
        assertEquals(listOf(-1, 3, 192, 192), input["shape"])
        assertEquals("fc1", output["name"])
        assertEquals("float32", output["data_type"])
        assertEquals(listOf(1, 212), output["shape"])
    }

    @Test
    fun `2d landmark graph uses embedded sub mul preprocessing`() {
        val preprocessing = inspectPackage().metadata["buffalo_l_2d_landmark_preprocessing"] as Map<*, *>
        assertEquals(true, preprocessing["graph_has_builtin_sub_mul"])
        assertEquals(0.0, preprocessing["mean"])
        assertEquals(1.0, preprocessing["std"])
        assertEquals(true, preprocessing["swap_rb"])
    }

    @Test
    fun `real 3d landmark graph contract is data and fc1 with 3309 dimensions`() {
        val contract = (inspectPackage().metadata["inference_contracts"] as Map<*, *>) ["landmark_3d"] as Map<*, *>
        val input = (contract["inputs"] as List<*>) [0] as Map<*, *>
        val output = (contract["outputs"] as List<*>) [0] as Map<*, *>
        assertEquals("data", input["name"])
        assertEquals("float32", input["data_type"])
        assertEquals(listOf(-1, 3, 192, 192), input["shape"])
        assertEquals("fc1", output["name"])
        assertEquals("float32", output["data_type"])
        assertEquals(listOf(1, 3309), output["shape"])
    }

    @Test
    fun `3d landmark graph uses external normalization branch`() {
        val preprocessing = inspectPackage().metadata["buffalo_l_3d_landmark_preprocessing"] as Map<*, *>
        assertEquals(false, preprocessing["graph_has_builtin_sub_mul"])
        assertEquals(127.5, preprocessing["mean"])
        assertEquals(128.0, preprocessing["std"])
        assertEquals(true, preprocessing["swap_rb"])
    }

    @Test
    fun `gender age role routes to genderage`() {
        val paths = inspectPackage().metadata["artifact_paths_by_role"] as Map<*, *>
        assertTrue(paths["gender_age"].toString().endsWith("genderage.onnx"))
        assertFalse(paths["gender_age"].toString().endsWith("1k3d68.onnx"))
    }

    @Test
    fun `real gender age graph contract is data and fc1 with three values`() {
        val contract = (inspectPackage().metadata["inference_contracts"] as Map<*, *>) ["gender_age"] as Map<*, *>
        val input = (contract["inputs"] as List<*>) [0] as Map<*, *>
        val output = (contract["outputs"] as List<*>) [0] as Map<*, *>
        assertEquals("data", input["name"])
        assertEquals("float32", input["data_type"])
        assertEquals(listOf(-1, 3, 96, 96), input["shape"])
        assertEquals("fc1", output["name"])
        assertEquals("float32", output["data_type"])
        assertEquals(listOf(1, 3), output["shape"])
    }

    @Test
    fun `gender age graph uses embedded sub mul preprocessing`() {
        val preprocessing = inspectPackage().metadata["buffalo_l_gender_age_preprocessing"] as Map<*, *>
        assertEquals(true, preprocessing["graph_has_builtin_sub_mul"])
        assertEquals(0.0, preprocessing["mean"])
        assertEquals(1.0, preprocessing["std"])
        assertEquals(true, preprocessing["swap_rb"])
    }

    @Test
    fun `gender age uses the shared bbox crop at 96 pixels`() {
        val transform = InsightFaceLandmarkAlignment.fromBoundingBox(FaceBoundingBox(10f, 20f, 110f, 220f), 96)
        assertEquals(0.32f, transform.scale, 1e-6f)
        assertEquals(48f, transform.map(FacePoint(60f, 120f)).x, 1e-4f)
        assertEquals(48f, transform.map(FacePoint(60f, 120f)).y, 1e-4f)
    }

    @Test
    fun `gender age decoder follows official argmax and age rounding`() {
        assertEquals(1, decodeGenderAge(listOf(0.2f, 0.8f, 0.27f)).genderIndex)
        assertEquals(27, decodeGenderAge(listOf(0.2f, 0.8f, 0.27f)).age)
        assertEquals(0, decodeGenderAge(listOf(0.8f, 0.2f, 0.276f)).genderIndex)
        assertEquals(28, decodeGenderAge(listOf(0.8f, 0.2f, 0.276f)).age)
    }

    @Test
    fun `invalid gender age outputs are rejected`() {
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(genderAgeModel(listOf(1, 2)), "gender_age") }
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(genderAgeModel(listOf(1, 4)), "gender_age") }
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(genderAgeModel(listOf(1, 1, 3)), "gender_age") }
    }

    @Test
    fun `2d landmark crop transform matches official bbox geometry`() {
        val transform = InsightFaceLandmarkAlignment.fromBoundingBox(FaceBoundingBox(10f, 20f, 110f, 220f))
        assertEquals(0.64f, transform.scale, 1e-6f)
        assertEquals(96f, transform.map(FacePoint(60f, 120f)).x, 1e-4f)
        assertEquals(96f, transform.map(FacePoint(60f, 120f)).y, 1e-4f)
        assertEquals(60f, transform.inverseMap(FacePoint(96f, 96f)).x, 1e-4f)
        assertEquals(120f, transform.inverseMap(FacePoint(96f, 96f)).y, 1e-4f)
    }

    @Test
    fun `2d landmark output produces 106 source points`() {
        val output = List(212) { 0f }
        val points = InsightFaceLandmarkAlignment.modelOutputToSourceCoordinates(
            output,
            InsightFaceLandmarkAlignment.fromBoundingBox(FaceBoundingBox(0f, 0f, 192f, 192f)),
        )
        assertEquals(106, points.size)
        assertEquals(96f, points.first().x, 1e-4f)
        assertEquals(96f, points.first().y, 1e-4f)
    }

    @Test
    fun `2d landmark model coordinates use plus one and half target conversion`() {
        val points = InsightFaceLandmarkAlignment.modelOutputToCropCoordinates(List(212) { index -> if (index % 2 == 0) 1f else -1f })
        assertEquals(FacePoint(192f, 0f), points.first())
        assertEquals(106, points.size)
    }

    @Test
    fun `3d decoder keeps the last 68 rows and scales xyz officially`() {
        val output = List(3309) { index ->
            val row = index / 3
            when (index % 3) {
                0 -> if (row < 1035) -1f else 0f
                1 -> if (row < 1035) -1f else 0.5f
                else -> if (row < 1035) 1f else 2f
            }
        }
        val points = InsightFaceLandmarkAlignment.model3dOutputToSourceCoordinates(
            output,
            InsightFaceLandmarkAlignment.fromBoundingBox(FaceBoundingBox(0f, 0f, 192f, 192f)),
        )
        assertEquals(68, points.size)
        assertEquals(FacePoint3d(96f, 168f, 288f), points.first())
        assertEquals(FacePoint3d(96f, 168f, 288f), points.last())
    }

    @Test
    fun `invalid 3d landmark output dimensions are rejected`() {
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(landmark3dModel(listOf(1, 3308)), "landmark_3d") }
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(landmark3dModel(listOf(1, 3310)), "landmark_3d") }
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(landmark3dModel(listOf(1, 1, 3309)), "landmark_3d") }
    }

    @Test
    fun `invalid 2d landmark output dimensions are rejected`() {
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(landmark2dModel(listOf(1, 211)), "landmark_2d") }
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(landmark2dModel(listOf(1, 213)), "landmark_2d") }
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(landmark2dModel(listOf(1, 1, 212)), "landmark_2d") }
    }

    @Test
    fun `real ArcFace graph contract is input 1 and output 683 with 512 dimensions`() {
        val inspection = inspectPackage()
        val contract = (inspection.metadata["inference_contracts"] as Map<*, *>) ["face_embedding"] as Map<*, *>
        val input = (contract["inputs"] as List<*>).single() as Map<*, *>
        val output = (contract["outputs"] as List<*>).single() as Map<*, *>
        assertEquals("input.1", input["name"])
        assertEquals("float32", input["data_type"])
        assertEquals(listOf(-1, 3, 112, 112), input["shape"])
        assertEquals("683", output["name"])
        assertEquals("float32", output["data_type"])
        assertEquals(listOf(1, 512), output["shape"])
    }

    @Test
    fun `ArcFace preprocessing uses external 127 point 5 normalization branch`() {
        val inspection = inspectPackage()
        val preprocessing = inspection.metadata["buffalo_l_embedding_preprocessing"] as Map<*, *>
        assertEquals(false, preprocessing["graph_has_builtin_sub_mul"])
        assertEquals(127.5, preprocessing["mean"])
        assertEquals(127.5, preprocessing["std"])
        assertEquals(true, preprocessing["swap_rb"])
    }

    @Test
    fun `ArcFace template and identity similarity transform are exact`() {
        assertEquals(listOf(FacePoint(38.2946f, 51.6963f), FacePoint(73.5318f, 51.5014f), FacePoint(56.0252f, 71.7366f), FacePoint(41.5493f, 92.3655f), FacePoint(70.7299f, 92.2041f)), ArcFaceAlignment.TEMPLATE)
        val transform = ArcFaceAlignment.estimateSimilarityTransform(ArcFaceAlignment.TEMPLATE)
        ArcFaceAlignment.TEMPLATE.forEach { point ->
            val mapped = transform.map(point)
            assertEquals(point.x, mapped.x, 1e-4f)
            assertEquals(point.y, mapped.y, 1e-4f)
        }
    }

    @Test
    fun `ArcFace similarity transform maps scaled translated landmarks`() {
        val source = ArcFaceAlignment.TEMPLATE.map { FacePoint(it.x * 2f + 10f, it.y * 2f - 5f) }
        val transform = ArcFaceAlignment.estimateSimilarityTransform(source)
        ArcFaceAlignment.TEMPLATE.forEachIndexed { index, point ->
            val mapped = transform.map(source[index])
            assertEquals(point.x, mapped.x, 1e-3f)
            assertEquals(point.y, mapped.y, 1e-3f)
        }
    }

    @Test
    fun `face embedding output preserves raw 512D and normalized vectors`() {
        val model = arcFaceModel(listOf(1, 512))
        val contract = ModelInferenceContract.resolve(model, "face_embedding")
        val raw = List(512) { (it + 1).toFloat() }
        val result = RuntimeOutputMapper.toResult(
            AiExecutionRequest("s", "t", "face_embedding", "buffalo_l", "1", "onnx", 1, 0L, emptyMap()),
            model,
            contract,
            mapOf("683" to raw),
            "onnx",
        )
        val details = result.details["result"] as Map<*, *>
        assertEquals(raw, details["raw_embedding"])
        val normalized = details["normalized_embedding"] as List<*>
        assertEquals(1.0, sqrt(normalized.sumOf { (it as Number).toDouble() * it.toDouble() }), 1e-5)
    }

    @Test
    fun `zero face embedding normalization is finite`() {
        assertTrue(normalizeL2(List(512) { 0f }).all { it == 0f && it.isFinite() })
    }

    @Test
    fun `invalid ArcFace output dimensions are rejected`() {
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(arcFaceModel(listOf(1, 511)), "face_embedding") }
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(arcFaceModel(listOf(1, 513)), "face_embedding") }
        assertThrows(IllegalArgumentException::class.java) { ModelInferenceContract.resolve(arcFaceModel(listOf(1, 1, 512)), "face_embedding") }
    }

    @Test
    fun `Buffalo readiness exposes detection and face embedding only`() {
        val capabilities = inspectPackage().metadata["buffalo_l_capabilities"] as Map<*, *>
        assertEquals(true, (capabilities["face_detection"] as Map<*, *>) ["ready"])
        assertEquals(true, (capabilities["face_embedding"] as Map<*, *>) ["ready"])
        assertEquals(true, (capabilities["landmark_2d"] as Map<*, *>) ["ready"])
        assertEquals(true, (capabilities["landmark_3d"] as Map<*, *>) ["ready"])
        assertEquals(false, (capabilities["pose"] as Map<*, *>) ["ready"])
        assertEquals(true, (capabilities["gender_age"] as Map<*, *>) ["ready"])
    }

    private fun arcFaceModel(outputShape: List<Int>): AiModelDescriptor = AiModelDescriptor(
        "buffalo_l",
        "1",
        "Buffalo-L",
        0L,
        "",
        listOf("face_embedding"),
        "onnx",
        listOf("onnx"),
        emptyList(),
        emptyMap(),
        emptyMap(),
        mapOf("inference_contracts" to mapOf("face_embedding" to mapOf(
            "tokenizer" to mapOf("type" to "none"),
            "image_preprocessing" to mapOf("enabled" to true, "width" to 112, "height" to 112, "channels" to 3, "color_space" to "rgb", "resize_mode" to "similarity", "scale" to 1.0, "mean" to listOf(127.5), "std" to listOf(127.5)),
            "inputs" to listOf(mapOf("name" to "input.1", "source" to "image", "data_type" to "float32", "layout" to "nchw", "shape" to listOf(-1, 3, 112, 112))),
            "outputs" to listOf(mapOf("name" to "683", "index" to 0, "data_type" to "float32", "shape" to outputShape)),
            "output_decoder" to mapOf("type" to "embedding", "output_name" to "683", "hidden_dimension" to 512),
            "confidence_scoring" to mapOf("type" to "identity", "threshold" to 0.0),
        ))),
        "",
        "",
        true,
        "installed",
        "buffalo.onnx",
        0L,
        0L,
    )

    private fun landmark2dModel(outputShape: List<Int>): AiModelDescriptor = arcFaceModel(outputShape).copy(
        supportedTasks = listOf("landmark_2d"),
        metadata = mapOf("inference_contracts" to mapOf("landmark_2d" to mapOf(
            "tokenizer" to mapOf("type" to "none"),
            "image_preprocessing" to mapOf("enabled" to true, "width" to 192, "height" to 192, "channels" to 3, "color_space" to "rgb", "resize_mode" to "similarity", "scale" to 1.0, "mean" to listOf(0.0), "std" to listOf(1.0)),
            "inputs" to listOf(mapOf("name" to "data", "source" to "image", "data_type" to "float32", "layout" to "nchw", "shape" to listOf(-1, 3, 192, 192))),
            "outputs" to listOf(mapOf("name" to "fc1", "index" to 0, "data_type" to "float32", "shape" to outputShape)),
            "output_decoder" to mapOf("type" to "landmarks_2d", "output_name" to "fc1", "hidden_dimension" to 212),
            "confidence_scoring" to mapOf("type" to "identity", "threshold" to 0.0),
        ))))

    private fun landmark3dModel(outputShape: List<Int>): AiModelDescriptor = arcFaceModel(outputShape).copy(
        supportedTasks = listOf("landmark_3d"),
        metadata = mapOf("inference_contracts" to mapOf("landmark_3d" to mapOf(
            "tokenizer" to mapOf("type" to "none"),
            "image_preprocessing" to mapOf("enabled" to true, "width" to 192, "height" to 192, "channels" to 3, "color_space" to "rgb", "resize_mode" to "similarity", "scale" to 1.0, "mean" to listOf(127.5), "std" to listOf(128.0)),
            "inputs" to listOf(mapOf("name" to "data", "source" to "image", "data_type" to "float32", "layout" to "nchw", "shape" to listOf(-1, 3, 192, 192))),
            "outputs" to listOf(mapOf("name" to "fc1", "index" to 0, "data_type" to "float32", "shape" to outputShape)),
            "output_decoder" to mapOf("type" to "landmarks_3d", "output_name" to "fc1", "hidden_dimension" to 3309),
            "confidence_scoring" to mapOf("type" to "identity", "threshold" to 0.0),
        ))))

    private fun genderAgeModel(outputShape: List<Int>): AiModelDescriptor = arcFaceModel(outputShape).copy(
        supportedTasks = listOf("gender_age"),
        metadata = mapOf("inference_contracts" to mapOf("gender_age" to mapOf(
            "tokenizer" to mapOf("type" to "none"),
            "image_preprocessing" to mapOf("enabled" to true, "width" to 96, "height" to 96, "channels" to 3, "color_space" to "rgb", "resize_mode" to "similarity", "scale" to 1.0, "mean" to listOf(0.0), "std" to listOf(1.0)),
            "inputs" to listOf(mapOf("name" to "data", "source" to "image", "data_type" to "float32", "layout" to "nchw", "shape" to listOf(-1, 3, 96, 96))),
            "outputs" to listOf(mapOf("name" to "fc1", "index" to 0, "data_type" to "float32", "shape" to outputShape)),
            "output_decoder" to mapOf("type" to "gender_age", "output_name" to "fc1", "hidden_dimension" to 3),
            "confidence_scoring" to mapOf("type" to "identity", "threshold" to 0.0),
        ))))

    private fun inspectPackage(): ModelPackageInspection =
        ModelPackageInspector().inspect(packageDirectory, File("build/buffalo-l-extracted"))
}
