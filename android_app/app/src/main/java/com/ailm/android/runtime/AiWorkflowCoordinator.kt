package com.ailm.android.runtime

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject

class AiWorkflowCoordinator(
    private val database: LocalDatabase,
    private val repository: LocalRepository,
) {
    fun applyImageWorkflow(imageId: Int, response: Map<String, Any>): Map<String, Any> {
        if (!response["ok"].asBoolean()) return mapOf("accepted" to false, "reason" to "pipeline_failed")

        val stages = collectStages(response)
        val accepted = mutableListOf<String>()
        val reviewReasons = mutableListOf<String>()
        response["failed_stages"].mapList().forEach { failed ->
            val stage = failed.optText("stage_type").ifBlank { "stage" }
            val message = failed.optText("message").ifBlank { failed.optText("status") }
            reviewReasons += "Automation stage failed: $stage${if (message.isBlank()) "" else " ($message)"}"
        }
        val profile = readProfile(imageId)
        if (!profile.optBoolean("manual_override", false) && profile.optJSONObject("normalization")?.optBoolean("manual_override", false) != true) {
            stages["ocr"]?.resultMap()?.optText("text")?.takeIf { it.isNotBlank() }?.let { profile.put("ocr", it) }
            stages["captioning"]?.resultMap()?.optText("caption")?.takeIf { it.isNotBlank() }?.let { profile.put("caption", it) }
            stages["embedding_generation"]?.get("embedding")?.let { profile.put("embedding", JSONArray(it as? List<*> ?: emptyList<Any>())) }
            stages["nsfw_classification"]?.resultMap()?.let { nsfw -> profile.put("nsfw", JSONObject(nsfw)) }
            stages["normalization"]?.resultMap()?.optText("text")?.takeIf { it.isNotBlank() }?.let {
                profile.put("normalized_context", it)
            }
            profile.put("ai_workflow_updated_at_ms", System.currentTimeMillis())
            writeProfile(imageId, profile)
        }

        val acceptedCharacter = acceptRecognition(
            imageId,
            stages["character_recognition"],
            FusionDatabaseSchema.TABLE_CHARACTERS,
            "character_id",
            "canonical_name",
            FusionDatabaseSchema.TABLE_IMAGE_CHARACTERS,
            accepted,
            reviewReasons,
        )
        val originalCharacter = isExplicitOriginalCharacter(stages["series_recognition"])
        val acceptedSeries = if (originalCharacter) {
            accepted += "series_recognition"
            null
        } else {
            acceptRecognition(
                imageId,
                stages["series_recognition"],
                FusionDatabaseSchema.TABLE_SERIES,
                "series_code",
                "canonical_title",
                FusionDatabaseSchema.TABLE_IMAGE_SERIES,
                accepted,
                reviewReasons,
            )
        }

        val tags = stages["tag_prediction"]?.resultMap()?.stringList("tags").orEmpty()
        if (tags.isNotEmpty()) {
            val canonicalTags = tags.mapNotNull { tag -> linkCanonicalTag(imageId, tag) }.distinct()
            if (canonicalTags.isNotEmpty()) {
                repository.setTags(imageId, canonicalTags)
                accepted += "tag_prediction"
            }
            profile.put("raw_predicted_tags", JSONArray(tags))
            profile.put("canonical_tags", JSONArray(canonicalTags))
            profile.put("ai_workflow_updated_at_ms", System.currentTimeMillis())
            writeProfile(imageId, profile)
        }

        stages["aesthetic_scoring"]?.resultMap()?.get("aesthetic_score")?.let { score ->
            profile.put("aesthetic_score", score)
            profile.put("ai_workflow_updated_at_ms", System.currentTimeMillis())
            writeProfile(imageId, profile)
        }

        if (reviewReasons.isNotEmpty()) queueReview(imageId, reviewReasons.joinToString("; "))
        repository.rebuildSearchIndex()
        return mapOf(
            "accepted" to accepted.isNotEmpty(),
            "accepted_stages" to accepted.distinct(),
            "accepted_series_code" to acceptedSeries?.first.orEmpty(),
            "accepted_series_name" to acceptedSeries?.second.orEmpty(),
            "accepted_character_id" to acceptedCharacter?.first.orEmpty(),
            "accepted_character_name" to acceptedCharacter?.second.orEmpty(),
            "original_character" to originalCharacter,
            "queued_for_review" to reviewReasons.isNotEmpty(),
            "review_reasons" to reviewReasons,
        )
    }

    private fun isExplicitOriginalCharacter(stage: Map<String, Any>?): Boolean {
        val result = stage?.resultMap() ?: return false
        if (result["original_character"].asBoolean() || result["is_original_character"].asBoolean()) return true
        val candidate = result["candidates"].mapList().firstOrNull()
        val name = candidate?.optText("name").orEmpty().ifBlank { result.optText("top_match") }
        if (name.isBlank()) return false
        val normalized = name.trim().lowercase()
        val explicitOriginal = normalized in setOf(
            "original character",
            "original characters",
            "original_character",
            "original",
            "oc",
        )
        if (!explicitOriginal) return false
        val confidence = candidate?.get("confidence").asDouble().takeIf { it > 0.0 }
            ?: result["confidence"].asDouble()
        return confidence >= ACCEPTANCE_THRESHOLD
    }

    private fun acceptRecognition(
        imageId: Int,
        stage: Map<String, Any>?,
        entityTable: String,
        entityIdColumn: String,
        entityNameColumn: String,
        linkTable: String,
        accepted: MutableList<String>,
        reviewReasons: MutableList<String>,
    ): Pair<String, String>? {
        val result = stage?.resultMap() ?: return null
        val candidate = result["candidates"].mapList().firstOrNull() ?: mapOf("name" to result.optText("top_match"), "confidence" to 0.0)
        val name = candidate.optText("name").ifBlank { result.optText("top_match") }
        val confidence = candidate["confidence"].asDouble()
        if (name.isBlank() || confidence < ACCEPTANCE_THRESHOLD) {
            if (name.isNotBlank()) reviewReasons += "Low-confidence recognition: $name (${formatConfidence(confidence)})"
            return null
        }
        val entityId = resolveEntityId(entityTable, entityIdColumn, entityNameColumn, name) ?: run {
            reviewReasons += "Unresolved canonical recognition: $name"
            return null
        }
        val values = ContentValues().apply {
            put("image_id", imageId)
            put(entityIdColumn, entityId)
            put("confidence", confidence)
            put("source", "ai")
            put("added_at_ms", System.currentTimeMillis())
        }
        database.writableDatabase.insertWithOnConflict(linkTable, null, values, SQLiteDatabase.CONFLICT_IGNORE)
        accepted += stage["task_type"]?.toString().orEmpty()
        return entityId to name
    }

    private fun linkCanonicalTag(imageId: Int, rawTag: String): String? {
        val tag = rawTag.trim()
        if (tag.isBlank()) return null
        val resolved = resolveTagEntry(tag) ?: return null
        val values = ContentValues().apply {
            put("image_id", imageId)
            put("tag_id", resolved.first)
            put("confidence", 0.8)
            put("source", "ai")
            put("added_at_ms", System.currentTimeMillis())
        }
        database.writableDatabase.insertWithOnConflict(
            FusionDatabaseSchema.TABLE_IMAGE_TAGS,
            null,
            values,
            SQLiteDatabase.CONFLICT_IGNORE,
        )
        return resolved.second
    }

    private fun resolveTagEntry(name: String): Pair<String, String>? {
        val normalized = name.trim()
        if (normalized.isBlank()) return null
        database.readableDatabase.rawQuery(
            "SELECT tag_id, canonical_name FROM ${FusionDatabaseSchema.TABLE_TAGS} WHERE LOWER(canonical_name) = LOWER(?) LIMIT 1",
            arrayOf(normalized),
        ).use { cursor ->
            if (cursor.moveToFirst()) return cursor.getString(0) to cursor.getString(1)
        }
        database.readableDatabase.rawQuery(
            """
            SELECT t.tag_id, t.canonical_name
            FROM ${FusionDatabaseSchema.TABLE_TAG_ALIASES} a
            JOIN ${FusionDatabaseSchema.TABLE_TAGS} t ON t.tag_id = a.tag_id
            WHERE LOWER(a.alias_value) = LOWER(?)
            LIMIT 1
            """.trimIndent(),
            arrayOf(normalized),
        ).use { cursor ->
            if (cursor.moveToFirst()) return cursor.getString(0) to cursor.getString(1)
        }
        return null
    }

    private fun resolveEntityId(table: String, idColumn: String, nameColumn: String, name: String): String? {
        val normalized = name.trim()
        if (normalized.isBlank() || normalized.equals("UNKNOWN", ignoreCase = true)) return null

        database.readableDatabase.rawQuery(
            "SELECT $idColumn FROM $table WHERE LOWER($nameColumn) = LOWER(?) LIMIT 1",
            arrayOf(normalized),
        ).use { cursor ->
            if (cursor.moveToFirst()) {
                return cursor.getString(0).orEmpty().ifBlank { null }
            }
        }

        if (table == FusionDatabaseSchema.TABLE_SERIES) {
            database.readableDatabase.rawQuery(
                "SELECT series_code, aliases_json FROM ${FusionDatabaseSchema.TABLE_SERIES}",
                emptyArray(),
            ).use { cursor ->
                while (cursor.moveToNext()) {
                    val aliases = runCatching { JSONArray(cursor.getString(1).orEmpty()) }.getOrNull() ?: continue
                    for (index in 0 until aliases.length()) {
                        if (aliases.optString(index).trim().equals(normalized, ignoreCase = true)) {
                            return cursor.getString(0).orEmpty().ifBlank { null }
                        }
                    }
                }
            }
        }

        if (table == FusionDatabaseSchema.TABLE_TAGS) {
            database.readableDatabase.rawQuery(
                "SELECT tag_id FROM ${FusionDatabaseSchema.TABLE_TAG_ALIASES} WHERE LOWER(alias_value) = LOWER(?) LIMIT 1",
                arrayOf(normalized),
            ).use { cursor ->
                if (cursor.moveToFirst()) return cursor.getString(0).orEmpty().ifBlank { null }
            }
        }

        return null
    }

    private fun readProfile(imageId: Int): JSONObject = database.readableDatabase.rawQuery(
        "SELECT metadata_json FROM ${FusionDatabaseSchema.TABLE_IMAGE_PROFILES} WHERE image_id = ? LIMIT 1",
        arrayOf(imageId.toString()),
    ).use { cursor -> if (cursor.moveToFirst()) runCatching { JSONObject(cursor.getString(0).orEmpty()) }.getOrElse { JSONObject() } else JSONObject() }

    private fun writeProfile(imageId: Int, metadata: JSONObject) {
        val values = ContentValues().apply {
            put("image_id", imageId)
            put("source_uri", repository.searchByImageId(imageId)?.get("uri")?.toString().orEmpty())
            put("metadata_json", metadata.toString())
            put("updated_at_ms", System.currentTimeMillis())
        }
        database.writableDatabase.insertWithOnConflict(FusionDatabaseSchema.TABLE_IMAGE_PROFILES, null, values, SQLiteDatabase.CONFLICT_REPLACE)
    }

    private fun queueReview(imageId: Int, reason: String) {
        val imageUri = repository.searchByImageId(imageId)?.get("uri")?.toString().orEmpty()
        if (imageUri.isBlank()) return
        val values = ContentValues().apply {
            put("status", "pending")
            put("reason", reason)
            put("last_updated_ms", System.currentTimeMillis())
        }
        val changed = database.writableDatabase.update("review_items", values, "image_uri = ? AND status != 'approved'", arrayOf(imageUri))
        if (changed == 0) {
            values.put("image_uri", imageUri)
            database.writableDatabase.insertWithOnConflict("review_items", null, values, SQLiteDatabase.CONFLICT_IGNORE)
        }
    }

    private fun collectStages(response: Map<String, Any>): Map<String, Map<String, Any>> {
        val stages = linkedMapOf<String, Map<String, Any>>()

        val explicitOutputs = response["stage_outputs"] as? Map<*, *>
        explicitOutputs?.forEach { (stageKey, rawOutput) ->
            val stageType = stageKey?.toString()?.trim().orEmpty()
            val output = (rawOutput as? Map<*, *>)
                ?.entries
                ?.filter { it.key != null && it.value != null }
                ?.associate { it.key.toString() to it.value as Any }
                .orEmpty()
            if (stageType.isNotBlank() && output.isNotEmpty()) {
                stages[stageType] = if (output["task_type"] == null) {
                    output + mapOf("task_type" to stageType)
                } else {
                    output
                }
            }
        }

        fun visit(value: Any?) {
            when (value) {
                is Map<*, *> -> {
                    val map = value.entries.filter { it.key != null && it.value != null }.associate { it.key.toString() to it.value as Any }
                    val type = map["task_type"]?.toString()?.trim().orEmpty()
                    if (type.isNotBlank()) stages.putIfAbsent(type, map)
                    map.values.forEach(::visit)
                }
                is List<*> -> value.forEach(::visit)
            }
        }
        visit(response)
        return stages
    }

    private fun Map<String, Any>.resultMap(): Map<String, Any> = (this["result"] as? Map<*, *>)?.entries
        ?.filter { it.key != null && it.value != null }?.associate { it.key.toString() to it.value as Any } ?: this
    private fun Map<String, Any>.optText(key: String): String = this[key]?.toString()?.trim().orEmpty()
    private fun Map<String, Any>.stringList(key: String): List<String> = (this[key] as? List<*>)?.mapNotNull { it?.toString()?.trim()?.takeIf(String::isNotBlank) }.orEmpty()
    private fun Any?.mapList(): List<Map<String, Any>> = (this as? List<*>)?.mapNotNull { item ->
        (item as? Map<*, *>)?.entries?.filter { it.key != null && it.value != null }?.associate { it.key.toString() to it.value as Any }
    }.orEmpty()
    private fun Any?.asBoolean(): Boolean = this as? Boolean ?: this?.toString()?.equals("true", ignoreCase = true) == true
    private fun Any?.asDouble(): Double = (this as? Number)?.toDouble() ?: this?.toString()?.toDoubleOrNull() ?: 0.0
    private fun formatConfidence(value: Double): String = "%.2f".format(value.coerceIn(0.0, 1.0))

    private companion object { const val ACCEPTANCE_THRESHOLD = 0.75 }
}