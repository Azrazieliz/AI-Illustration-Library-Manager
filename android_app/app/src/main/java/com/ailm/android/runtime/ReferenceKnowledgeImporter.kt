package com.ailm.android.runtime

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject
import java.io.InputStream
import java.util.Locale
import java.util.zip.ZipInputStream

internal data class ReferenceSeriesEntry(
    val code: String,
    val name: String,
    val franchise: String,
    val aliases: List<String>,
)

internal data class ReferenceTagEntry(
    val id: String,
    val name: String,
    val category: String,
    val parentId: String,
    val aliases: List<String>,
)

internal data class ReferenceKnowledgeBundle(
    val series: List<ReferenceSeriesEntry>,
    val tags: List<ReferenceTagEntry>,
)

internal object ReferenceKnowledgeParser {
    fun parseDocuments(documents: Map<String, String>): ReferenceKnowledgeBundle {
        val series = linkedMapOf<String, ReferenceSeriesEntry>()
        val tags = linkedMapOf<String, ReferenceTagEntry>()
        documents.toSortedMap(String.CASE_INSENSITIVE_ORDER).forEach { (filename, raw) ->
            collectObjects(raw).forEach { obj ->
                val canonicalName = obj.optString("canonical_name").trim()
                if (canonicalName.isBlank()) return@forEach
                val seriesCode = obj.optString("series_code").trim()
                if (seriesCode.isNotBlank()) {
                    series.putIfAbsent(
                        seriesCode.lowercase(Locale.US),
                        ReferenceSeriesEntry(
                            code = seriesCode,
                            name = canonicalName,
                            franchise = obj.optString("franchise").trim(),
                            aliases = stringList(obj.optJSONArray("aliases")),
                        ),
                    )
                } else {
                    val id = obj.optString("tag_id").trim().ifBlank { obj.optString("id").trim() }
                    if (id.isBlank()) return@forEach
                    val parent = listOf("parent_tag", "parent_action", "parent_outfit", "parent_weapon")
                        .asSequence()
                        .map { obj.optString(it).trim() }
                        .firstOrNull(String::isNotBlank)
                        .orEmpty()
                    tags.putIfAbsent(
                        id.lowercase(Locale.US),
                        ReferenceTagEntry(
                            id = id,
                            name = canonicalName,
                            category = inferCategory(filename, obj),
                            parentId = parent,
                            aliases = stringList(obj.optJSONArray("aliases")),
                        ),
                    )
                }
            }
        }
        return ReferenceKnowledgeBundle(series.values.toList(), tags.values.toList())
    }

    private fun collectObjects(raw: String): List<JSONObject> {
        val trimmed = raw.trim()
        if (trimmed.startsWith("[")) {
            val array = JSONArray(trimmed)
            return (0 until array.length()).mapNotNull(array::optJSONObject)
        }
        val root = JSONObject(trimmed)
        if (root.has("canonical_name")) return listOf(root)
        return buildList {
            root.keys().forEach { key ->
                when (val value = root.opt(key)) {
                    is JSONArray -> for (index in 0 until value.length()) {
                        value.optJSONObject(index)?.let(::add)
                    }
                    is JSONObject -> if (value.has("canonical_name")) add(value)
                }
            }
        }
    }

    private fun inferCategory(filename: String, obj: JSONObject): String {
        obj.optString("attribute").trim().takeIf(String::isNotBlank)?.let { return slug(it) }
        val lower = filename.lowercase(Locale.US)
        return when {
            "outfit" in lower -> "outfit"
            "weapon" in lower -> "weapon"
            "hair" in lower -> "hair"
            "eye" in lower && "mouth" !in lower -> "eyes"
            "mouth" in lower -> "eye_mouth_state"
            "skin" in lower -> "skin"
            "body" in lower -> "body"
            "age" in lower -> "age"
            "species" in lower -> "species"
            "expression" in lower -> "expression"
            "gesture" in lower -> "gesture"
            "pose" in lower -> "pose"
            "environment" in lower || "weather" in lower -> "environment"
            "framing" in lower || "camera" in lower || "lighting" in lower -> "camera_framing"
            "action" in lower || obj.has("parent_action") -> "action"
            else -> "tag"
        }
    }

    private fun slug(value: String): String = value.trim().lowercase(Locale.US)
        .replace(Regex("[^a-z0-9]+"), "_").trim('_')

    private fun stringList(array: JSONArray?): List<String> {
        if (array == null) return emptyList()
        return (0 until array.length()).mapNotNull { index ->
            array.optString(index).trim().takeIf(String::isNotBlank)
        }
    }
}

internal class ReferenceKnowledgeImporter(
    private val database: LocalDatabase,
) {
    fun importZip(input: InputStream, sourceName: String): Map<String, Any> {
        val documents = linkedMapOf<String, String>()
        ZipInputStream(input).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                if (!entry.isDirectory && entry.name.lowercase(Locale.US).endsWith(".json")) {
                    documents[entry.name.substringAfterLast('/')] = zip.readBytes().toString(Charsets.UTF_8)
                }
                zip.closeEntry()
            }
        }
        if (documents.isEmpty()) {
            return mapOf("ok" to false, "message" to "No JSON knowledge files were found in $sourceName.")
        }
        return importBundle(ReferenceKnowledgeParser.parseDocuments(documents), sourceName)
    }

    private fun importBundle(bundle: ReferenceKnowledgeBundle, sourceName: String): Map<String, Any> {
        val db = database.writableDatabase
        var seriesInserted = 0
        var tagsInserted = 0
        var aliasesInserted = 0
        val now = System.currentTimeMillis()

        db.beginTransaction()
        try {
            bundle.series.forEachIndexed { index, entry ->
                val values = ContentValues().apply {
                    put("series_code", entry.code)
                    putNull("franchise_id")
                    putNull("parent_series_code")
                    put("canonical_title", entry.name)
                    put("localized_title", "")
                    put("aliases_json", JSONArray(entry.aliases).toString())
                    put("metadata_json", JSONObject(mapOf(
                        "source" to "reference_knowledge_archive",
                        "source_archive" to sourceName,
                        "franchise" to entry.franchise,
                    )).toString())
                    put("workbook_row", index + 1)
                    put("created_at_ms", now)
                    put("updated_at_ms", now)
                }
                if (db.insertWithOnConflict(
                        FusionDatabaseSchema.TABLE_SERIES,
                        null,
                        values,
                        SQLiteDatabase.CONFLICT_IGNORE,
                    ) != -1L
                ) seriesInserted += 1
            }

            bundle.tags.forEachIndexed { index, entry ->
                val values = ContentValues().apply {
                    put("tag_id", entry.id)
                    put("canonical_name", entry.name)
                    put("category", entry.category)
                    putNull("parent_tag_id")
                    put("metadata_json", JSONObject(mapOf(
                        "source" to "reference_knowledge_archive",
                        "source_archive" to sourceName,
                    )).toString())
                    put("workbook_row", index + 1)
                    put("created_at_ms", now)
                    put("updated_at_ms", now)
                }
                if (db.insertWithOnConflict(
                        FusionDatabaseSchema.TABLE_TAGS,
                        null,
                        values,
                        SQLiteDatabase.CONFLICT_IGNORE,
                    ) != -1L
                ) tagsInserted += 1
            }

            bundle.tags.forEach { entry ->
                if (entry.parentId.isNotBlank()) {
                    db.execSQL(
                        "UPDATE ${FusionDatabaseSchema.TABLE_TAGS} SET parent_tag_id = ? WHERE tag_id = ? AND EXISTS (SELECT 1 FROM ${FusionDatabaseSchema.TABLE_TAGS} WHERE tag_id = ?)",
                        arrayOf(entry.parentId, entry.id, entry.parentId),
                    )
                }
                entry.aliases.distinct().forEach { alias ->
                    val aliasValues = ContentValues().apply {
                        put("alias_id", "ref:${entry.id}:${alias.lowercase(Locale.US).replace(Regex("[^a-z0-9]+"), "-").trim('-')}")
                        put("tag_id", entry.id)
                        put("alias_value", alias)
                        put("locale", "")
                        put("created_at_ms", now)
                    }
                    if (db.insertWithOnConflict(
                            FusionDatabaseSchema.TABLE_TAG_ALIASES,
                            null,
                            aliasValues,
                            SQLiteDatabase.CONFLICT_IGNORE,
                        ) != -1L
                    ) aliasesInserted += 1
                }
            }

            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }

        return mapOf(
            "ok" to true,
            "message" to "Reference knowledge imported.",
            "kind" to "reference_knowledge_archive",
            "source" to sourceName,
            "series_entries" to bundle.series.size,
            "tag_entries" to bundle.tags.size,
            "series_inserted" to seriesInserted,
            "tags_inserted" to tagsInserted,
            "aliases_inserted" to aliasesInserted,
            "characters_imported" to 0,
        )
    }
}
