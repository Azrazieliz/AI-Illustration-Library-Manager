package com.ailm.android.runtime.ai

import org.json.JSONArray
import org.json.JSONObject

object LocalAiJson {
    fun encodeMap(map: Map<String, Any?>): String {
        return toJsonObject(map).toString()
    }

    fun encodeList(values: List<Any?>): String {
        return toJsonArray(values).toString()
    }

    fun decodeMap(raw: String): Map<String, Any> {
        val normalized = raw.removePrefix("\uFEFF")
        if (normalized.isBlank()) {
            return emptyMap()
        }
        if (normalized.trimStart().startsWith("{")) {
            val platformParsed = runCatching { fromJsonObject(JSONObject(normalized)) }.getOrNull()
            if (platformParsed != null) {
                return platformParsed
            }
            return decodeObjectFallback(normalized)
        }
        return runCatching { fromJsonObject(JSONObject(normalized)) }
            .getOrElse { emptyMap() }
    }

    fun decodeList(raw: String): List<Any> {
        if (raw.isBlank()) {
            return emptyList()
        }
        return runCatching { fromJsonArray(JSONArray(raw)) }
            .getOrElse { emptyList() }
    }

    fun toJsonValue(value: Any?): Any? {
        return when (value) {
            null -> JSONObject.NULL
            is JSONObject, is JSONArray -> value
            is Map<*, *> -> {
                val mapped = mutableMapOf<String, Any?>()
                value.forEach { (k, v) ->
                    val key = k?.toString() ?: return@forEach
                    mapped[key] = v
                }
                toJsonObject(mapped)
            }
            is Iterable<*> -> toJsonArray(value.toList())
            is Array<*> -> toJsonArray(value.toList())
            is Number, is Boolean, is String -> value
            else -> value.toString()
        }
    }

    fun fromJsonValue(value: Any?): Any? {
        return when (value) {
            null, JSONObject.NULL -> null
            is JSONObject -> fromJsonObject(value)
            is JSONArray -> fromJsonArray(value)
            else -> value
        }
    }

    private fun toJsonObject(map: Map<String, Any?>): JSONObject {
        val obj = JSONObject()
        map.forEach { (key, value) ->
            obj.put(key, toJsonValue(value))
        }
        return obj
    }

    private fun toJsonArray(values: List<Any?>): JSONArray {
        val array = JSONArray()
        values.forEach { value ->
            array.put(toJsonValue(value))
        }
        return array
    }

    private fun fromJsonObject(obj: JSONObject): Map<String, Any> {
        val result = linkedMapOf<String, Any>()
        val keys = obj.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val value = fromJsonValue(obj.opt(key))
            if (value != null) {
                result[key] = value
            }
        }
        return result
    }

    private fun fromJsonArray(array: JSONArray): List<Any> {
        val result = mutableListOf<Any>()
        for (index in 0 until safeArrayLength(array)) {
            val value = fromJsonValue(array.opt(index))
            if (value != null) {
                result += value
            }
        }
        return result
    }

    private fun safeArrayLength(array: JSONArray): Int {
        return try {
            array.length()
        } catch (_: RuntimeException) {
            var count = 0
            while (runCatching { array.opt(count) }.getOrNull() != null) {
                count += 1
            }
            count
        }
    }

    private fun decodeObjectFallback(raw: String): Map<String, Any> {
        val body = raw.trim().removePrefix("{").removeSuffix("}")
        return splitTopLevel(body, ',').mapNotNull { member ->
            val separator = findTopLevelSeparator(member, ':')
            if (separator < 0) return@mapNotNull null
            val key = decodeString(member.substring(0, separator).trim()) ?: return@mapNotNull null
            val value = decodeFallbackValue(member.substring(separator + 1).trim()) ?: return@mapNotNull null
            key to value
        }.toMap()
    }

    private fun decodeFallbackValue(raw: String): Any? = when {
        raw.startsWith("{") -> decodeObjectFallback(raw)
        raw.startsWith("[") -> splitTopLevel(raw.removePrefix("[").removeSuffix("]"), ',')
            .filter(String::isNotBlank)
            .mapNotNull { decodeFallbackValue(it.trim()) }
        raw.startsWith("\"") -> decodeString(raw)
        raw == "true" -> true
        raw == "false" -> false
        raw == "null" -> null
        raw.contains('.') -> raw.toFloatOrNull()
        else -> raw.toLongOrNull() ?: raw
    }

    private fun decodeString(raw: String): String? {
        val value = raw.trim()
        if (value.length < 2 || value.first() != '"' || value.last() != '"') return null
        return buildString {
            var escaped = false
            value.substring(1, value.length - 1).forEach { character ->
                if (escaped) {
                    append(
                        when (character) {
                            'n' -> '\n'
                            'r' -> '\r'
                            't' -> '\t'
                            '\\' -> '\\'
                            '"' -> '"'
                            else -> character
                        },
                    )
                    escaped = false
                } else if (character == '\\') {
                    escaped = true
                } else {
                    append(character)
                }
            }
        }
    }

    private fun splitTopLevel(raw: String, delimiter: Char): List<String> {
        val result = mutableListOf<String>()
        var start = 0
        var depth = 0
        var inString = false
        var escaped = false
        raw.forEachIndexed { index, character ->
            when {
                escaped -> escaped = false
                inString && character == '\\' -> escaped = true
                inString && character == '"' -> inString = false
                !inString && character == '"' -> inString = true
                !inString && character in "[{" -> depth += 1
                !inString && character in "]}" -> depth -= 1
                !inString && character == delimiter && depth == 0 -> {
                    result += raw.substring(start, index)
                    start = index + 1
                }
            }
        }
        result += raw.substring(start)
        return result
    }

    private fun findTopLevelSeparator(raw: String, delimiter: Char): Int {
        var depth = 0
        var inString = false
        var escaped = false
        raw.forEachIndexed { index, character ->
            when {
                escaped -> escaped = false
                inString && character == '\\' -> escaped = true
                inString && character == '"' -> inString = false
                !inString && character == '"' -> inString = true
                !inString && character in "[{" -> depth += 1
                !inString && character in "]}" -> depth -= 1
                !inString && character == delimiter && depth == 0 -> return index
            }
        }
        return -1
    }
}
