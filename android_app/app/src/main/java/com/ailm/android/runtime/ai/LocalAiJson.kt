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
        if (raw.isBlank()) {
            return emptyMap()
        }
        return runCatching { fromJsonObject(JSONObject(raw)) }
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
        for (index in 0 until array.length()) {
            val value = fromJsonValue(array.opt(index))
            if (value != null) {
                result += value
            }
        }
        return result
    }
}
