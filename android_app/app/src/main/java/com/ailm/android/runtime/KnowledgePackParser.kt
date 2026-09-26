package com.ailm.android.runtime

import org.json.JSONArray
import org.json.JSONObject
import com.ailm.android.runtime.ai.LocalAiJson
import java.security.MessageDigest
import java.util.Locale

class KnowledgePackParser {
    fun parse(raw: String): ParsedKnowledgePack {
        val trimmed = raw.trim()
        if (trimmed.startsWith("[")) {
            return parseRawArray(trimmed)
        }
        val rootObject = JSONObject(trimmed)

        val metadata = rootObject.optJSONObject("metadata") ?: JSONObject()
        val manifest = rootObject.optJSONObject("pack") ?: rootObject.optJSONObject("manifest") ?: JSONObject()
        val packMetadata = mergeObjects(metadata, manifest)

        val packId = firstNonBlank(
            rootObject.optString("pack_id"), 
            packMetadata.optString("pack_id"),
            rootObject.optString("knowledge_pack_id"),
            rootObject.optString("id"),
        )
        val packName = firstNonBlank(
            rootObject.optString("pack_name"),
            packMetadata.optString("pack_name"),
            rootObject.optString("name"),
            packId,
        )
        val version = firstNonBlank(rootObject.optString("version"), packMetadata.optString("version"), "1.0.0")
        val knowledgeType = firstNonBlank(
            rootObject.optString("knowledge_type"),
            packMetadata.optString("knowledge_type"),
            rootObject.optString("type"),
            packMetadata.optString("type"),
            rootObject.optString("domain"),
            packMetadata.optString("domain"),
            "unknown",
        )
        val author = firstNonBlank(rootObject.optString("author"), packMetadata.optString("author"), "Unknown")
        val creationDate = firstNonBlank(
            rootObject.optString("creation_date"),
            packMetadata.optString("creation_date"),
            packMetadata.optString("created_at"),
            packMetadata.optString("created"),
            "Unknown",
        )
        val description = firstNonBlank(rootObject.optString("description"), packMetadata.optString("description"), "")
        val dependencies = parseStringList(rootObject.optJSONArray("dependencies") ?: packMetadata.optJSONArray("dependencies"))
        val supportedCategories = parseStringList(rootObject.optJSONArray("supported_categories") ?: packMetadata.optJSONArray("supported_categories"))
        val entriesArray = selectEntriesArray(rootObject)

        val entries = mutableListOf<ParsedKnowledgeEntry>()
        for (index in 0 until safeArrayLength(entriesArray)) {
            val entryObject = entriesArray.optJSONObject(index) ?: continue
            entries += parseEntry(index, entryObject)
        }

        return ParsedKnowledgePack(
            packId = packId,
            packName = packName,
            version = version,
            knowledgeType = knowledgeType.lowercase(Locale.US),
            author = author,
            creationDate = creationDate,
            description = description,
            dependencies = dependencies,
            supportedCategories = supportedCategories.ifEmpty { inferCategories(entries) },
            entries = entries,
            rawMetadata = mergeObjects(rootObject, packMetadata).toMap(),
        )
    }

    private fun parseArray(array: JSONArray, rawSource: String): ParsedKnowledgePack {
        val entries = mutableListOf<ParsedKnowledgeEntry>()
        val arrayLength = safeArrayLength(array)
        if (arrayLength > 0) {
            for (index in 0 until arrayLength) {
                val entryObject = array.optJSONObject(index) ?: continue
                entries += parseEntry(index, entryObject)
            }
        } else {
            topLevelObjects(rawSource).forEachIndexed { index, objectText ->
                runCatching { JSONObject(objectText) }.getOrNull()?.let { entryObject ->
                    entries += parseEntry(index, entryObject)
                }
            }
        }
        val rawHash = sha256Hex(rawSource.toByteArray()).substring(0, 16)
        return ParsedKnowledgePack(
            packId = "inline-array-$rawHash",
            packName = "Inline Array Pack",
            version = "1.0.0",
            knowledgeType = "unknown",
            author = "Unknown",
            creationDate = "Unknown",
            description = "",
            dependencies = emptyList(),
            supportedCategories = inferCategories(entries),
            entries = entries,
            rawMetadata = emptyMap(),
        )
    }

    private fun parseRawArray(rawSource: String): ParsedKnowledgePack {
        val entries = topLevelObjects(rawSource).mapIndexedNotNull { index, objectText ->
            parseRawEntry(index, objectText)
        }
        val rawHash = sha256Hex(rawSource.toByteArray()).substring(0, 16)
        return ParsedKnowledgePack(
            packId = "inline-array-$rawHash",
            packName = "Inline Array Pack",
            version = "1.0.0",
            knowledgeType = "unknown",
            author = "Unknown",
            creationDate = "Unknown",
            description = "",
            dependencies = emptyList(),
            supportedCategories = inferCategories(entries),
            entries = entries,
            rawMetadata = emptyMap(),
        )
    }

    private fun parseRawEntry(index: Int, objectText: String): ParsedKnowledgeEntry? {
        val properties = LocalAiJson.decodeMap(objectText)
        if (properties.isEmpty()) return null
        return ParsedKnowledgeEntry(
            index = index,
            raw = ParsedJsonObject(properties),
            id = properties["id"].stringValue(),
            name = properties["name"].stringValue(),
            categories = properties["categories"].stringListValue(),
            taxonomy = ParsedJsonObject(properties["taxonomy"].mapValue()),
            metadata = ParsedJsonObject(properties["metadata"].mapValue()),
            aliases = properties["aliases"].stringListValue(),
            tags = properties["tags"].stringListValue(),
            relationships = emptyList(),
            rawProperties = properties,
        )
    }

    private fun safeArrayLength(array: JSONArray): Int {
        return try {
            array.length()
        } catch (_: RuntimeException) {
            var count = 0
            while (runCatching { array.optJSONObject(count) }.getOrNull() != null) {
                count += 1
            }
            count
        }
    }

    private fun topLevelObjects(rawSource: String): List<String> {
        val objects = mutableListOf<String>()
        var depth = 0
        var start = -1
        var inString = false
        var escaped = false
        rawSource.forEachIndexed { index, character ->
            when {
                escaped -> escaped = false
                inString && character == '\\' -> escaped = true
                inString && character == '"' -> inString = false
                !inString && character == '"' -> inString = true
                !inString && character == '{' -> {
                    if (depth == 0) start = index
                    depth += 1
                }
                !inString && character == '}' -> {
                    depth -= 1
                    if (depth == 0 && start >= 0) {
                        objects += rawSource.substring(start, index + 1)
                        start = -1
                    }
                }
            }
        }
        return objects
    }

    private fun parseEntry(index: Int, entryObject: JSONObject): ParsedKnowledgeEntry {
        val id = firstNonBlank(
            entryObject.optString("id"),
            entryObject.optString("canonical_id"),
            entryObject.optString("knowledge_id"),
            entryObject.optString("entry_id"),
        )
        val name = firstNonBlank(
            entryObject.optString("name"),
            entryObject.optString("canonical_name"),
            entryObject.optString("character_name"),
            entryObject.optString("title"),
        )
        val taxonomy = entryObject.optJSONObject("taxonomy") ?: JSONObject()
        val metadata = entryObject.optJSONObject("metadata") ?: JSONObject()
        val aliases = parseStringList(entryObject.optJSONArray("aliases"))
        val tags = parseStringList(entryObject.optJSONArray("tags"))
        val relationships = parseRelationships(entryObject.optJSONArray("relationships"))
        return ParsedKnowledgeEntry(
            index = index,
            raw = entryObject,
            id = id,
            name = name,
            categories = parseStringList(entryObject.optJSONArray("categories")),
            taxonomy = taxonomy,
            metadata = metadata,
            aliases = aliases,
            tags = tags,
            relationships = relationships,
            rawProperties = runCatching { entryObject.toMap() }.getOrDefault(emptyMap()),
        )
    }

    private fun selectEntriesArray(root: JSONObject): JSONArray {
        for (key in listOf("entries", "characters", "items", "taxonomy_entries", "tags", "entities")) {
            val array = root.optJSONArray(key)
            if (array != null && safeArrayLength(array) > 0) {
                return array
            }
        }
        return JSONArray()
    }

    private fun parseRelationships(array: JSONArray?): List<ParsedKnowledgeRelationship> {
        if (array == null) return emptyList()
        return buildList {
            for (index in 0 until safeArrayLength(array)) {
                val item = array.optJSONObject(index) ?: continue
                val target = firstNonBlank(
                    item.optString("target_id"),
                    item.optString("target"),
                    item.optString("id"),
                )
                val relation = firstNonBlank(item.optString("relation"), item.optString("kind"), item.optString("type"), "related")
                add(ParsedKnowledgeRelationship(targetId = target, relation = relation))
            }
        }
    }

    private fun inferCategories(entries: List<ParsedKnowledgeEntry>): List<String> {
        return entries.flatMap { entry -> entry.categories }.distinct().sorted()
    }

    private fun firstNonBlank(vararg values: String): String {
        return values.firstOrNull { it.isNotBlank() } ?: ""
    }

    private fun parseStringList(array: JSONArray?): List<String> {
        if (array == null) return emptyList()
        return buildList {
            for (index in 0 until safeArrayLength(array)) {
                val value = array.optString(index).trim()
                if (value.isNotBlank()) add(value)
            }
        }
    }

    private fun mergeObjects(first: JSONObject, second: JSONObject): JSONObject {
        val merged = JSONObject()
        val allKeys = mutableListOf<String>()
        allKeys += first.keys().asSequence().toList()
        allKeys += second.keys().asSequence().toList()
        allKeys.distinct().forEach { key ->
            val value = first.opt(key)
            val fallback = second.opt(key)
            merged.put(key, if (value != null && value != JSONObject.NULL && (value as? String)?.isNotBlank() == true) value else fallback)
        }
        return merged
    }

    private fun sha256Hex(data: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(data)
        return hash.joinToString("") { "%02x".format(it) }
    }
}

private fun Any?.stringValue(): String = (this as? String).orEmpty()

private fun Any?.stringListValue(): List<String> = (this as? List<*>)
    ?.mapNotNull { (it as? String)?.trim()?.takeIf(String::isNotBlank) }
    .orEmpty()

private fun Any?.mapValue(): Map<String, Any> = when (this) {
    is Map<*, *> -> entries.mapNotNull { (key, value) ->
        key?.toString()?.let { textKey -> value?.let { textKey to it } }
    }.toMap()
    else -> emptyMap()
}

private class ParsedJsonObject(
    private val values: Map<String, Any>,
) : JSONObject() {
    override fun has(name: String): Boolean = values.containsKey(name)

    override fun length(): Int = values.size

    override fun opt(name: String): Any? = values[name]

    override fun optString(name: String): String = values[name]?.toString().orEmpty()

    override fun optString(name: String, fallback: String): String = values[name]?.toString() ?: fallback
}

data class ParsedKnowledgePack(
    val packId: String,
    val packName: String,
    val version: String,
    val knowledgeType: String,
    val author: String,
    val creationDate: String,
    val description: String,
    val dependencies: List<String>,
    val supportedCategories: List<String>,
    val entries: List<ParsedKnowledgeEntry>,
    val rawMetadata: Map<String, Any>,
)

data class ParsedKnowledgeEntry(
    val index: Int,
    val raw: JSONObject,
    val id: String,
    val name: String,
    val categories: List<String>,
    val taxonomy: JSONObject,
    val metadata: JSONObject,
    val aliases: List<String>,
    val tags: List<String>,
    val relationships: List<ParsedKnowledgeRelationship>,
    val rawProperties: Map<String, Any>,
)

data class ParsedKnowledgeRelationship(
    val targetId: String,
    val relation: String,
)

fun JSONObject.toMap(): Map<String, Any> {
    val result = linkedMapOf<String, Any>()
    val keys = this.keys()
    while (keys.hasNext()) {
        val key = keys.next()
        result[key] = this.opt(key)
    }
    return result
}
