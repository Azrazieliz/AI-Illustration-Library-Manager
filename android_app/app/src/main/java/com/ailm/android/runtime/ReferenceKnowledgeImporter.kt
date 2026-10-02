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
    val characters: List<KnowledgeCharacterEntry> = emptyList(),
)

internal object ReferenceKnowledgeParser {
    fun looksLikeReferenceDocument(filename: String, raw: String): Boolean {
        return runCatching {
            collectObjects(raw).any { obj ->
                val canonicalName = obj.optString("canonical_name").trim()
                    .ifBlank { obj.optString("character_name").trim() }
                if (canonicalName.isBlank()) {
                    false
                } else {
                    val explicitReferenceId = listOf(
                        "series_code",
                        "tag_id",
                        "character_id",
                        "outfit_id",
                        "weapon_id",
                    ).any { key -> obj.optString(key).trim().isNotBlank() }
                    val genericTaxonomyId = obj.optString("id").trim().isNotBlank() &&
                        (
                            obj.optString("attribute").trim().isNotBlank() ||
                                obj.has("parent_tag") ||
                                obj.has("parent_action") ||
                                obj.has("parent_outfit") ||
                                obj.has("parent_weapon") ||
                                inferCategory(filename, obj) != "tag"
                            )
                    explicitReferenceId || genericTaxonomyId
                }
            }
        }.getOrDefault(false)
    }

    fun parseDocuments(documents: Map<String, String>): ReferenceKnowledgeBundle {
        val series = linkedMapOf<String, ReferenceSeriesEntry>()
        val tags = linkedMapOf<String, ReferenceTagEntry>()
        val characters = linkedMapOf<String, KnowledgeCharacterEntry>()
        documents.toSortedMap(String.CASE_INSENSITIVE_ORDER).forEach { (filename, raw) ->
            collectObjects(raw).forEach { obj ->
                val canonicalName = obj.optString("canonical_name").trim()
                    .ifBlank { obj.optString("character_name").trim() }
                if (canonicalName.isBlank()) return@forEach

                val characterId = obj.optString("character_id").trim()
                if (characterId.isNotBlank()) {
                    val primarySeries = obj.optString("primary_series_code").trim()
                        .ifBlank { obj.optString("series_code").trim() }
                    val attributes = linkedSetOf<String>().apply {
                        addAll(stringList(obj.optJSONArray("attribute_ids")))
                        val attributeObject = obj.optJSONObject("attributes")
                        attributeObject?.keys()?.forEach { key ->
                            when (val value = attributeObject.opt(key)) {
                                is JSONArray -> addAll(stringList(value))
                                is String -> value.trim().takeIf(String::isNotBlank)?.let(::add)
                            }
                        }
                    }
                    characters.putIfAbsent(
                        characterId.lowercase(Locale.US),
                        KnowledgeCharacterEntry(
                            characterId = characterId,
                            parentCharacterId = obj.optString("parent_character_id").trim(),
                            identityGroupId = obj.optString("identity_group_id").trim(),
                            entryType = obj.optString("entry_type").trim().ifBlank {
                                if (obj.optString("parent_character_id").isNotBlank()) "transformation" else "identity"
                            },
                            canonicalName = canonicalName,
                            primarySeriesCode = primarySeries,
                            aliases = stringList(obj.optJSONArray("aliases")),
                            attributeIds = attributes.toList(),
                            weaponIds = stringList(obj.optJSONArray("canonical_weapon_ids"))
                                .ifEmpty { stringList(obj.optJSONArray("weapon_ids")) },
                            outfitIds = stringList(obj.optJSONArray("canonical_outfit_ids"))
                                .ifEmpty { stringList(obj.optJSONArray("outfit_ids")) },
                            sheetAssetId = obj.optString("sheet_asset_id").trim(),
                            metadata = emptyMap(),
                        ),
                    )
                    return@forEach
                }

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
        return ReferenceKnowledgeBundle(
            series = series.values.toList(),
            tags = tags.values.toList(),
            characters = characters.values.toList(),
        )
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
    private val knowledgeDatabase: KnowledgeDatabase,
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
        return importDocuments(documents, sourceName)
    }

    fun importDocuments(documents: Map<String, String>, sourceName: String): Map<String, Any> {
        if (documents.isEmpty()) {
            return mapOf("ok" to false, "message" to "No Knowledge JSON documents were supplied.")
        }

        val bundle = ReferenceKnowledgeParser.parseDocuments(documents)
        if (bundle.series.isEmpty() && bundle.tags.isEmpty() && bundle.characters.isEmpty()) {
            return mapOf("ok" to false, "message" to "No supported Knowledge entries were found in $sourceName.")
        }

        return runCatching {
            if (bundle.series.isNotEmpty() || bundle.tags.isNotEmpty()) {
                require(bundle.series.isNotEmpty() && bundle.tags.isNotEmpty()) {
                    "A reference taxonomy release must contain both canonical series and taxonomy values. Select the series JSON and taxonomy JSON files together."
                }
                knowledgeDatabase.replaceReferenceKnowledge(
                    ReferenceKnowledgeBundle(bundle.series, bundle.tags),
                    sourceName,
                )
            }
            if (bundle.characters.isNotEmpty()) {
                knowledgeDatabase.replaceCharacterKnowledge(bundle.characters, sourceName)
            }
            mapOf(
                "ok" to true,
                "message" to "Immutable Knowledge release imported.",
                "kind" to "immutable_knowledge_release",
                "source" to sourceName,
                "documents" to documents.size,
                "series_entries" to bundle.series.size,
                "tag_entries" to bundle.tags.size,
                "character_entries" to bundle.characters.size,
                "characters_imported" to bundle.characters.size,
                "fusion_modified" to false,
            )
        }.getOrElse { error ->
            mapOf(
                "ok" to false,
                "message" to (error.message ?: error.javaClass.simpleName),
                "kind" to "immutable_knowledge_release",
                "source" to sourceName,
            )
        }
    }
}
