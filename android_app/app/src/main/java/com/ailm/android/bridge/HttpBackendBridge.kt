package com.ailm.android.bridge

import android.net.Uri
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject.NULL
import org.json.JSONObject

class HttpBackendBridge : AndroidBackendBridge {

    private val backendBaseUrl: String
        get() = BackendDiscovery.getBaseUrl()

    private val client = OkHttpClient()

    private val jsonType = "application/json".toMediaType()

    private fun getJson(path: String): JSONObject {
        val request = Request.Builder()
            .url("$backendBaseUrl$path")
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("HTTP ${response.code} calling $path")
            }
            return JSONObject(response.body!!.string())
        }
    }

    override fun getBaseUrl(): String = BackendDiscovery.getBaseUrl()

    override fun setBaseUrl(url: String) {
        BackendDiscovery.setConfiguredBaseUrl(url)
    }

    private fun postJsonArray(path: String, body: JSONObject): JSONArray {
        val request = Request.Builder()
            .url("$backendBaseUrl$path")
            .post(body.toString().toRequestBody(jsonType))
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("HTTP ${response.code} calling $path")
            }
            return JSONArray(response.body!!.string())
        }
    }

    private fun getJsonArray(path: String): JSONArray {
        val request = Request.Builder()
            .url("$backendBaseUrl$path")
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("HTTP ${response.code} calling $path")
            }
            return JSONArray(response.body!!.string())
        }
    }

    private fun postJson(path: String, body: JSONObject): JSONObject {
        val request = Request.Builder()
            .url("$backendBaseUrl$path")
            .post(body.toString().toRequestBody(jsonType))
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("HTTP ${response.code} calling $path")
            }
            return JSONObject(response.body!!.string())
        }
    }

    override fun healthStatus(): Map<String, Any> =
        getJson("/health").asMap()

    override fun libraryStatistics(): Map<String, Any> =
        getJson("/statistics").asMap()

    override fun startScan(root: String): Map<String, Any> =
        postJson("/scan/start", JSONObject().put("root", root)).asMap()

    override fun scanStatus(): Map<String, Any> =
        getJson("/scan/status").asMap()

    override fun pauseScan(): Boolean =
        postJson("/scan/pause", JSONObject()).optBoolean("ok", false)

    override fun resumeScan(): Boolean =
        postJson("/scan/resume", JSONObject()).optBoolean("ok", false)

    override fun cancelScan(): Boolean =
        postJson("/scan/cancel", JSONObject()).optBoolean("ok", false)

    override fun getCollections(
        query: String?,
        page: Int,
        pageSize: Int
    ): List<Map<String, Any>> {
        val queryPart = buildString {
            append("?page=$page&page_size=$pageSize")
            if (!query.isNullOrBlank()) {
                append("&query=${Uri.encode(query)}")
            }
        }

        val array = getJsonArray("/collections$queryPart")
        return List(array.length()) {
            array.getJSONObject(it).asMap()
        }
    }

    override fun getLibraryImages(
        query: String?,
        page: Int,
        pageSize: Int
    ): List<Map<String, Any>> {
        val queryPart = buildString {
            append("?page=$page&page_size=$pageSize")
            if (!query.isNullOrBlank()) {
                append("&query=${Uri.encode(query)}")
            }
        }

        val array = getJsonArray("/images$queryPart")

        return List(array.length()) { index ->
            val item = array.getJSONObject(index).asMap().toMutableMap()

            val path = item["path"]?.toString().orEmpty()
            val thumbnailPath = item["thumbnail_path"]?.toString()?.takeIf { it.isNotBlank() }

            if (path.isNotBlank()) {
                val encodedPath = Uri.encode(path)
                val fileUrl = "$backendBaseUrl/file?path=$encodedPath"
                item["file_url"] = fileUrl
                item["thumbnail_url"] = if (!thumbnailPath.isNullOrBlank()) {
                    "$backendBaseUrl/file?path=${Uri.encode(thumbnailPath)}"
                } else {
                    fileUrl
                }
            }

            item
        }
    }

    override fun getTags(): List<String> {
        val array = getJsonArray("/tags")
        return List(array.length()) {
            array.getString(it)
        }
    }

    override fun searchByFilename(query: String): List<Map<String, Any>> {
        val body = JSONObject()
            .put("query", query)

        val response = postJson("/search/filename", body)
        val array = response.getJSONArray("results")

        return List(array.length()) {
            array.getJSONObject(it).asMap()
        }
    }

    override fun semanticSearch(queryVector: List<Float>): List<Map<String, Any>> {
        val body = JSONObject()
            .put("query_vector", JSONArray(queryVector))

        val response = postJson("/search/semantic", body)
        val array = response.getJSONArray("results")

        return List(array.length()) {
            array.getJSONObject(it).asMap()
        }
    }

    override fun advancedSearch(payload: Map<String, Any>) =
        postJson("/search/advanced", JSONObject().put("payload", JSONObject(payload))).asMap()

    override fun getReviewQueue() =
        getJsonArray("/review/queue").toMapList()

    override fun updateReview(
        itemId: String,
        action: String,
        payload: Map<String, Any>
    ): Boolean {
        val response = postJson(
            "/review/update",
            JSONObject()
                .put("item_id", itemId)
                .put("action", action)
                .put("payload", JSONObject(payload))
        )
        return response.optBoolean("updated", false)
    }

    override fun listKnowledgePacks() =
        getJsonArray("/knowledge/packs").toMapList()

    override fun listDownloads() =
        getJsonArray("/downloads").toMapList()

    override fun listPlugins() =
        getJsonArray("/plugins").toMapList()
}

private fun JSONObject.asMap(): Map<String, Any> {
    val map = mutableMapOf<String, Any>()

    val iterator = keys()
    while (iterator.hasNext()) {
        val key = iterator.next()
        map[key] = get(key).toKotlinValue()
    }

    return map
}

private fun JSONArray.toMapList(): List<Map<String, Any>> =
    List(length()) { index ->
        getJSONObject(index).asMap()
    }

private fun Any.toKotlinValue(): Any = when (this) {
    NULL -> ""
    is JSONObject -> asMap()
    is JSONArray -> List(length()) { idx -> get(idx).toKotlinValue() }
    else -> this
}