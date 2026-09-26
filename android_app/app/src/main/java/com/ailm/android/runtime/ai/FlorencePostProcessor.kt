package com.ailm.android.runtime.ai

private const val FLORENCE_LOCATION_BIN_COUNT = 1000

internal data class FlorenceParsedResult(
    val task: String,
    val rawDecodedText: String,
    val value: Map<String, Any>,
) {
    fun toMap(): Map<String, Any> = linkedMapOf(
        "task" to task,
        "raw_decoded_text" to rawDecodedText,
        "value" to value,
    )
}

internal object FlorencePostProcessor {
    private val localTaskTypes = linkedMapOf(
        "<OCR>" to "pure_text",
        "<OCR_WITH_REGION>" to "ocr",
        "<CAPTION>" to "pure_text",
        "<DETAILED_CAPTION>" to "pure_text",
        "<MORE_DETAILED_CAPTION>" to "pure_text",
        "<OD>" to "description_with_bboxes",
        "<DENSE_REGION_CAPTION>" to "description_with_bboxes",
        "<CAPTION_TO_PHRASE_GROUNDING>" to "phrase_grounding",
        "<REFERRING_EXPRESSION_SEGMENTATION>" to "polygons",
        "<REGION_TO_SEGMENTATION>" to "polygons",
        "<OPEN_VOCABULARY_DETECTION>" to "description_with_bboxes_or_polygons",
        "<REGION_TO_CATEGORY>" to "pure_text",
        "<REGION_TO_DESCRIPTION>" to "pure_text",
        "<REGION_TO_OCR>" to "pure_text",
        "<REGION_PROPOSAL>" to "bboxes",
    )

    private val locationPattern = Regex("<loc_(\\d+)>")
    private val boxPattern = Regex("<loc_(\\d+)><loc_(\\d+)><loc_(\\d+)><loc_(\\d+)>")
    private val quadPattern = Regex("(.+?)<loc_(\\d+)><loc_(\\d+)><loc_(\\d+)><loc_(\\d+)><loc_(\\d+)><loc_(\\d+)><loc_(\\d+)><loc_(\\d+)>")

    fun localTaskTokens(): List<String> = localTaskTypes.keys.toList()

    fun taskForPrompt(prompt: String?): String? = prompt?.let { source ->
        localTaskTypes.keys.firstOrNull { source.contains(it) }
    }

    fun process(task: String, rawDecodedText: String, imageWidth: Int?, imageHeight: Int?): FlorenceParsedResult {
        val postProcessingType = localTaskTypes[task]
            ?: throw ModelInferenceContractException("Florence task token is not supported locally: $task")
        val cleaned = rawDecodedText.replace("<s>", "").replace("</s>", "").replace("<pad>", "")
        val value = when (postProcessingType) {
            "pure_text" -> mapOf("text" to cleaned.trim())
            else -> {
                val width = imageWidth ?: throw ModelInferenceContractException("Florence structured task '$task' requires image_width")
                val height = imageHeight ?: throw ModelInferenceContractException("Florence structured task '$task' requires image_height")
                require(width > 0 && height > 0) { "Florence image dimensions must be positive" }
                parseStructured(postProcessingType, cleaned, width, height)
            }
        }
        return FlorenceParsedResult(task, rawDecodedText, value)
    }

    private fun parseStructured(type: String, text: String, width: Int, height: Int): Map<String, Any> = when (type) {
        "ocr" -> {
            val matches = quadPattern.findAll(text).toList()
            require(matches.isNotEmpty() || text.trim().isEmpty()) { "Malformed Florence OCR region output" }
            val boxes = matches.map { match ->
                val bins = match.groupValues.drop(2).map(String::toInt)
                dequantizePoints(bins, width, height)
            }
            mapOf("quad_boxes" to boxes, "labels" to matches.map { it.groupValues[1].trim() })
        }
        "phrase_grounding", "description_with_bboxes" -> {
            val instances = parseLabeledBoxes(text, width, height, allowEmptyLabel = false)
            mapOf(
                "bboxes" to instances.flatMap { it.first },
                "labels" to instances.flatMap { pair -> List(pair.first.size) { pair.second } },
            )
        }
        "bboxes" -> {
            val boxes = parseUnlabeledBoxes(text, width, height)
            mapOf("bboxes" to boxes, "labels" to emptyList<String>())
        }
        "polygons" -> {
            val instances = parsePolygons(text, width, height, allowEmptyLabel = true)
            mapOf("polygons" to instances.map { it.first }, "labels" to instances.map { it.second })
        }
        "description_with_bboxes_or_polygons" -> {
            if ("<poly>" in text) {
                val instances = parsePolygons(text, width, height, allowEmptyLabel = false)
                mapOf("bboxes" to emptyList<List<Int>>(), "bboxes_labels" to emptyList<String>(), "polygons" to instances.map { it.first }, "polygons_labels" to instances.map { it.second })
            } else {
                val instances = parseLabeledBoxes(text, width, height, allowEmptyLabel = false)
                mapOf("bboxes" to instances.flatMap { it.first }, "bboxes_labels" to instances.flatMap { pair -> List(pair.first.size) { pair.second } }, "polygons" to emptyList<List<Int>>(), "polygons_labels" to emptyList<String>())
            }
        }
        else -> error("Unsupported Florence post-processing type: $type")
    }

    private fun parseLabeledBoxes(text: String, width: Int, height: Int, allowEmptyLabel: Boolean): List<Pair<List<List<Int>>, String>> {
        val phrasePattern = Regex("([^<]+(?:(?:<loc_\\d+>)){4,})")
        val phrases = phrasePattern.findAll(text).map { it.groupValues[1] }.toList()
        val instances = phrases.mapNotNull { phraseText ->
            val firstLocation = locationPattern.find(phraseText)?.range?.first ?: return@mapNotNull null
            val label = phraseText.substring(0, firstLocation).replace("<ground>", "").replace("<obj>", "").trim()
            if (!allowEmptyLabel && label.isEmpty()) return@mapNotNull null
            val boxes = boxPattern.findAll(phraseText).map { match ->
                dequantizeBox(match.groupValues.drop(1).map(String::toInt), width, height)
            }.toList()
            if (boxes.isEmpty()) return@mapNotNull null
            boxes to label
        }
        require(instances.isNotEmpty() || text.trim().isEmpty()) { "Malformed Florence labeled box output" }
        require(locationPattern.findAll(text).count() == instances.sumOf { it.first.size * 4 }) {
            "Malformed Florence labeled box location sequence"
        }
        return instances
    }

    private fun parseUnlabeledBoxes(text: String, width: Int, height: Int): List<List<Int>> {
        val boxes = boxPattern.findAll(text).map { match ->
            dequantizeBox(match.groupValues.drop(1).map(String::toInt), width, height)
        }.toList()
        require(boxes.isNotEmpty() || text.trim().isEmpty()) { "Malformed Florence box output" }
        return boxes
    }

    private fun parsePolygons(text: String, width: Int, height: Int, allowEmptyLabel: Boolean): List<Pair<List<List<Int>>, String>> {
        val phrasePattern = Regex("([^<]*)<poly>(.*?)</poly>", setOf(RegexOption.DOT_MATCHES_ALL))
        val phrases = phrasePattern.findAll(text).map { it.groupValues[1].trim() to it.groupValues[2] }.toList()
        require(phrases.isNotEmpty() || text.trim().isEmpty()) { "Malformed Florence polygon output" }
        return phrases.map { (label, polygonText) ->
            require(allowEmptyLabel || label.isNotEmpty()) { "Florence polygon label is missing" }
            val polygons = polygonText.split("<sep>").map { polygon ->
                val bins = locationPattern.findAll(polygon).map { it.groupValues[1].toInt() }.toList()
                require(bins.size >= 6 && bins.size % 2 == 0) { "Florence polygon requires an even number of at least three points" }
                dequantizePoints(bins, width, height)
            }
            polygons to label
        }
    }

    private fun dequantizeBox(bins: List<Int>, width: Int, height: Int): List<Int> {
        require(bins.size == 4) { "Florence box requires four location bins" }
        return dequantizePoints(bins, width, height)
    }

    private fun dequantizePoints(bins: List<Int>, width: Int, height: Int): List<Int> {
        require(bins.size % 2 == 0) { "Florence location sequence must contain coordinate pairs" }
        require(bins.all { it in 0 until FLORENCE_LOCATION_BIN_COUNT }) { "Florence location bin is out of range" }
        return bins.mapIndexed { index, bin ->
            val size = if (index % 2 == 0) width else height
            ((bin + 0.5) * size / FLORENCE_LOCATION_BIN_COUNT).toInt()
        }
    }
}