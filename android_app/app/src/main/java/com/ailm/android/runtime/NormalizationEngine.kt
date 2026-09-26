package com.ailm.android.runtime

import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

class NormalizationEngine(
    private val database: LocalDatabase,
) {
    fun normalize(
        rowsByTable: MutableMap<String, MutableList<MutableMap<String, Any?>>>,
        source: String,
    ): List<String> {
        val warnings = mutableListOf<String>()
        val confidence = ConfidenceEngine(source)
        val aliases = AliasGenerator(rowsByTable)
        val seriesNormalizer = SeriesNormalizer(database, rowsByTable, aliases, confidence)
        val taxonomyMatcher = TaxonomyMatcher(database, rowsByTable, aliases, confidence)

        seriesNormalizer.normalizeSeriesRows(warnings)
        CharacterNormalizer(rowsByTable, seriesNormalizer, taxonomyMatcher, confidence).normalizeCharacters(warnings)
        RelationshipResolver(rowsByTable).resolve(warnings)
        return warnings
    }
}

private class ConfidenceEngine(
    private val source: String,
) {
    fun metadata(confidence: Double, reason: String): JSONObject = JSONObject().apply {
        put("confidence", confidence.coerceIn(0.0, 1.0))
        put("reason", reason)
        put("source", source)
        put("manual_override", false)
        put("automatic_override", true)
    }

    fun merge(existingJson: String, confidence: Double, reason: String): String {
        val existing = runCatching { JSONObject(existingJson) }.getOrElse { JSONObject() }
        existing.put("normalization", metadata(confidence, reason))
        return existing.toString()
    }
}

private class AliasGenerator(
    private val rowsByTable: MutableMap<String, MutableList<MutableMap<String, Any?>>>,
) {
    fun addTagAlias(tagId: String, alias: String) {
        val cleanAlias = alias.trim()
        if (tagId.isBlank() || cleanAlias.isBlank()) return
        val rows = rowsByTable.getOrPut(FusionDatabaseSchema.TABLE_TAG_ALIASES) { mutableListOf() }
        if (rows.any { it["tag_id"] == tagId && it["alias_value"]?.toString()?.equals(cleanAlias, ignoreCase = true) == true }) return
        rows += mutableMapOf(
            "alias_id" to "alias:${tagId}:${slug(cleanAlias)}",
            "tag_id" to tagId,
            "alias_value" to cleanAlias,
            "locale" to "",
            "created_at_ms" to System.currentTimeMillis(),
        )
    }

    fun addSeriesAlias(row: MutableMap<String, Any?>, alias: String) {
        val cleanAlias = alias.trim()
        if (cleanAlias.isBlank()) return
        val aliases = parseArray(row["aliases_json"]?.toString().orEmpty()).toMutableSet()
        aliases += cleanAlias
        row["aliases_json"] = JSONArray(aliases.sorted()).toString()
    }

    fun addCharacterAlias(row: MutableMap<String, Any?>, alias: String) {
        val cleanAlias = alias.trim()
        if (cleanAlias.isBlank()) return
        val profile = runCatching { JSONObject(row["recognition_profile_json"]?.toString().orEmpty()) }.getOrElse { JSONObject() }
        val aliases = parseArray(profile.optJSONArray("aliases")?.toString().orEmpty()).toMutableSet()
        aliases += cleanAlias
        profile.put("aliases", JSONArray(aliases.sorted()))
        row["recognition_profile_json"] = profile.toString()
    }
}

private class TaxonomyMatcher(
    private val database: LocalDatabase,
    private val rowsByTable: MutableMap<String, MutableList<MutableMap<String, Any?>>>,
    private val aliases: AliasGenerator,
    private val confidence: ConfidenceEngine,
) {
    fun resolve(category: String, rawValue: String): String {
        val raw = rawValue.trim()
        if (raw.isBlank()) return ""
        val normalized = normalizeLabel(raw)
        val candidates = canonicalTags(category)
        val exact = candidates.firstOrNull { normalizeLabel(it.second) == normalized }
        val closest = exact ?: candidates
            .map { candidate -> candidate to similarity(normalized, normalizeLabel(candidate.second)) }
            .filter { it.second >= 0.70 }
            .maxByOrNull { it.second }
            ?.first
        val resolved = closest ?: createCanonicalTag(category, canonicalDisplayName(raw))
        if (!resolved.second.equals(raw, ignoreCase = true)) aliases.addTagAlias(resolved.first, raw)
        return resolved.first
    }

    private fun canonicalTags(category: String): List<Pair<String, String>> {
        val rows = mutableListOf<Pair<String, String>>()
        database.readableDatabase.rawQuery(
            "SELECT tag_id, canonical_name FROM ${FusionDatabaseSchema.TABLE_TAGS} WHERE LOWER(category) = LOWER(?)",
            arrayOf(category),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0).orEmpty().trim()
                val name = cursor.getString(1).orEmpty().trim()
                if (id.isNotBlank() && name.isNotBlank()) rows += id to name
            }
        }
        rowsByTable[FusionDatabaseSchema.TABLE_TAGS].orEmpty().forEach { row ->
            if (row["category"]?.toString()?.equals(category, ignoreCase = true) == true) {
                val id = row["tag_id"]?.toString().orEmpty()
                val name = row["canonical_name"]?.toString().orEmpty()
                if (id.isNotBlank() && name.isNotBlank()) rows += id to name
            }
        }
        return rows.distinctBy { it.first }
    }

    private fun createCanonicalTag(category: String, displayName: String): Pair<String, String> {
        val id = "taxonomy:${slug(category)}:${slug(displayName)}"
        val tags = rowsByTable.getOrPut(FusionDatabaseSchema.TABLE_TAGS) { mutableListOf() }
        if (tags.none { it["tag_id"] == id }) {
            tags += mutableMapOf(
                "tag_id" to id,
                "canonical_name" to displayName,
                "category" to category,
                "parent_tag_id" to null,
                "metadata_json" to confidence.merge("", 0.65, "Created canonical taxonomy entry from external value"),
                "created_at_ms" to System.currentTimeMillis(),
                "updated_at_ms" to System.currentTimeMillis(),
            )
        }
        return id to displayName
    }
}

private class SeriesNormalizer(
    private val database: LocalDatabase,
    private val rowsByTable: MutableMap<String, MutableList<MutableMap<String, Any?>>>,
    private val aliases: AliasGenerator,
    private val confidence: ConfidenceEngine,
) {
    fun normalizeSeriesRows(warnings: MutableList<String>) {
        rowsByTable[FusionDatabaseSchema.TABLE_SERIES].orEmpty().forEach { row ->
            val title = firstText(row, "canonical_title", "series_name", "name", "title")
            if (title.isBlank()) {
                warnings += "Series row has no canonical title."
                return@forEach
            }
            val code = row["series_code"]?.toString()?.trim().orEmpty().ifBlank { "series:${slug(title)}" }
            row["series_code"] = code
            row["canonical_title"] = title
            aliases.addSeriesAlias(row, title)
            row["metadata_json"] = confidence.merge(row["metadata_json"]?.toString().orEmpty(), 0.92, "Normalized downloaded series to canonical ID")
        }
    }

    fun resolve(rawSeries: String): String {
        val raw = rawSeries.trim()
        if (raw.isBlank()) return ""
        val imported = rowsByTable[FusionDatabaseSchema.TABLE_SERIES].orEmpty().firstOrNull { row ->
            val title = row["canonical_title"]?.toString().orEmpty()
            val aliases = parseArray(row["aliases_json"]?.toString().orEmpty())
            normalizeLabel(title) == normalizeLabel(raw) || aliases.any { normalizeLabel(it) == normalizeLabel(raw) }
        }
        if (imported != null) return imported["series_code"]?.toString().orEmpty()

        val existing = database.readableDatabase.rawQuery(
            "SELECT series_code FROM ${FusionDatabaseSchema.TABLE_SERIES} WHERE LOWER(canonical_title) = LOWER(?) LIMIT 1",
            arrayOf(raw),
        ).use { cursor -> if (cursor.moveToFirst()) cursor.getString(0).orEmpty() else "" }
        if (existing.isNotBlank()) return existing

        val code = "series:${slug(raw)}"
        val rows = rowsByTable.getOrPut(FusionDatabaseSchema.TABLE_SERIES) { mutableListOf() }
        rows += mutableMapOf(
            "series_code" to code,
            "franchise_id" to null,
            "parent_series_code" to null,
            "canonical_title" to raw,
            "localized_title" to "",
            "aliases_json" to JSONArray(listOf(raw)).toString(),
            "metadata_json" to confidence.merge("", 0.68, "Created canonical series from downloaded character data"),
            "created_at_ms" to System.currentTimeMillis(),
            "updated_at_ms" to System.currentTimeMillis(),
        )
        return code
    }
}

private class CharacterNormalizer(
    private val rowsByTable: MutableMap<String, MutableList<MutableMap<String, Any?>>>,
    private val seriesNormalizer: SeriesNormalizer,
    private val taxonomyMatcher: TaxonomyMatcher,
    private val confidence: ConfidenceEngine,
) {
    fun normalizeCharacters(warnings: MutableList<String>) {
        rowsByTable[FusionDatabaseSchema.TABLE_CHARACTERS].orEmpty().forEach { row ->
            val characterName = firstText(row, "character_name", "canonical_name", "name")
            if (characterName.isBlank()) {
                warnings += "Character row has no Character Name."
                return@forEach
            }
            row["character_id"] = row["character_id"]?.toString()?.trim().orEmpty().ifBlank { "character:${slug(characterName)}" }
            row["canonical_name"] = characterName
            aliasesFrom(row, "aliases", "alternate_names").forEach { AliasGenerator(rowsByTable).addCharacterAlias(row, it) }

            val attributeIds = JSONObject()
            val series = firstText(row, "series", "series_name", "primary_series_code")
            if (series.isNotBlank()) {
                val seriesCode = seriesNormalizer.resolve(series)
                row["primary_series_code"] = seriesCode
                attributeIds.put("series", seriesCode)
                link(FusionDatabaseSchema.TABLE_CHARACTER_SERIES, mapOf("character_id" to row["character_id"], "series_code" to seriesCode, "relation_kind" to "primary"))
            }
            listOf("hair", "eyes", "age", "body", "species", "tags").forEach { category ->
                valuesFrom(row, category).map { taxonomyMatcher.resolve(category, it) }.filter { it.isNotBlank() }.let { ids ->
                    if (ids.isNotEmpty()) attributeIds.put(category, JSONArray(ids))
                }
            }
            normalizeNamedAsset(row, "outfit", FusionDatabaseSchema.TABLE_OUTFITS, "outfit_id", "canonical_name")?.let { outfitId ->
                attributeIds.put("outfit", outfitId)
                link(FusionDatabaseSchema.TABLE_CHARACTER_OUTFITS, mapOf("character_id" to row["character_id"], "outfit_id" to outfitId, "relation_kind" to "canonical"))
            }
            normalizeNamedAsset(row, "weapon", FusionDatabaseSchema.TABLE_WEAPONS, "weapon_id", "canonical_name")?.let { weaponId ->
                attributeIds.put("weapon", weaponId)
                link(FusionDatabaseSchema.TABLE_CHARACTER_WEAPONS, mapOf("character_id" to row["character_id"], "weapon_id" to weaponId, "relation_kind" to "canonical"))
            }

            val profile = runCatching { JSONObject(row["recognition_profile_json"]?.toString().orEmpty()) }.getOrElse { JSONObject() }
            profile.put("character_name", characterName)
            profile.put("attribute_ids", attributeIds)
            profile.put("normalization", confidence.metadata(0.86, "Normalized external character record to canonical IDs"))
            row["recognition_profile_json"] = profile.toString()
            row["metadata_json"] = confidence.merge(row["metadata_json"]?.toString().orEmpty(), 0.86, "Character normalization")
        }
    }

    private fun normalizeNamedAsset(row: MutableMap<String, Any?>, field: String, table: String, idColumn: String, nameColumn: String): String? {
        val value = firstText(row, field, "${field}_name", idColumn)
        if (value.isBlank()) return null
        val id = if (value.startsWith("$field:")) value else "$field:${slug(value)}"
        val rows = rowsByTable.getOrPut(table) { mutableListOf() }
        if (rows.none { it[idColumn] == id }) {
            rows += mutableMapOf(idColumn to id, nameColumn to value, "metadata_json" to confidence.merge("", 0.72, "Created canonical $field from character data"), "created_at_ms" to System.currentTimeMillis(), "updated_at_ms" to System.currentTimeMillis())
        }
        return id
    }

    private fun link(table: String, values: Map<String, Any?>) {
        val rows = rowsByTable.getOrPut(table) { mutableListOf() }
        if (rows.none { row -> values.all { (key, value) -> row[key] == value } }) {
            rows += values.toMutableMap().apply { put("added_at_ms", System.currentTimeMillis()) }
        }
    }
}

private class RelationshipResolver(
    private val rowsByTable: MutableMap<String, MutableList<MutableMap<String, Any?>>>,
) {
    fun resolve(warnings: MutableList<String>) {
        rowsByTable[FusionDatabaseSchema.TABLE_CHARACTERS].orEmpty().forEach { row ->
            val characterId = row["character_id"]?.toString().orEmpty()
            val seriesCode = row["primary_series_code"]?.toString().orEmpty()
            if (characterId.isNotBlank() && seriesCode.isNotBlank()) return@forEach
            if (characterId.isBlank()) warnings += "Character relationship cannot be resolved without character ID."
        }
    }
}

private fun firstText(row: Map<String, Any?>, vararg keys: String): String = keys.asSequence()
    .mapNotNull { row[it]?.toString()?.trim() }
    .firstOrNull { it.isNotBlank() }
    .orEmpty()

private fun valuesFrom(row: Map<String, Any?>, key: String): List<String> {
    val value = row[key] ?: row["${key}_values"] ?: return emptyList()
    return when (value) {
        is JSONArray -> buildList { for (index in 0 until value.length()) value.optString(index).trim().takeIf { it.isNotBlank() }?.let(::add) }
        else -> value.toString().split(',', '|').map { it.trim() }.filter { it.isNotBlank() }
    }
}

private fun aliasesFrom(row: Map<String, Any?>, vararg keys: String): List<String> = keys.flatMap { valuesFrom(row, it) }

private fun parseArray(raw: String): List<String> = runCatching {
    val array = JSONArray(raw)
    buildList { for (index in 0 until array.length()) array.optString(index).trim().takeIf { it.isNotBlank() }?.let(::add) }
}.getOrDefault(emptyList())

private fun normalizeLabel(raw: String): String = raw.lowercase(Locale.US)
    .replace("deep", "dark")
    .replace(Regex("[^a-z0-9]+"), " ")
    .trim()

private fun canonicalDisplayName(raw: String): String = normalizeLabel(raw)
    .split(' ')
    .filter { it.isNotBlank() }
    .joinToString(" ") { it.replaceFirstChar(Char::uppercaseChar) }

private fun slug(raw: String): String = normalizeLabel(raw).replace(' ', '-').ifBlank { "unknown" }

private fun similarity(left: String, right: String): Double {
    if (left == right) return 1.0
    val leftTokens = left.split(' ').filter { it.isNotBlank() }.toSet()
    val rightTokens = right.split(' ').filter { it.isNotBlank() }.toSet()
    if (leftTokens.isEmpty() || rightTokens.isEmpty()) return 0.0
    return leftTokens.intersect(rightTokens).size.toDouble() / leftTokens.union(rightTokens).size.toDouble()
}