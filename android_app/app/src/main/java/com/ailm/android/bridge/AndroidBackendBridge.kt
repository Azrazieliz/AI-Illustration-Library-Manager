package com.ailm.android.bridge

interface AndroidBackendBridge {
    fun healthStatus(): Map<String, Any>
    fun libraryStatistics(): Map<String, Any>
    fun getCollections(query: String? = null, page: Int = 1, pageSize: Int = 50): List<Map<String, Any>>
    fun getTags(): List<String>
    fun searchByFilename(query: String): List<Map<String, Any>>
    fun semanticSearch(queryVector: List<Float>): List<Map<String, Any>>
    fun advancedSearch(payload: Map<String, Any>): Map<String, Any>
    fun getReviewQueue(): List<Map<String, Any>>
    fun updateReview(itemId: String, action: String, payload: Map<String, Any> = emptyMap()): Boolean
    fun listKnowledgePacks(): List<Map<String, Any>>
    fun listDownloads(): List<Map<String, Any>>
    fun listPlugins(): List<Map<String, Any>>
}

class NoOpBackendBridge : AndroidBackendBridge {
    override fun healthStatus(): Map<String, Any> = mapOf("healthy" to true)
    override fun libraryStatistics(): Map<String, Any> = mapOf("total_images" to 0)
    override fun getCollections(query: String?, page: Int, pageSize: Int): List<Map<String, Any>> = emptyList()
    override fun getTags(): List<String> = emptyList()
    override fun searchByFilename(query: String): List<Map<String, Any>> = emptyList()
    override fun semanticSearch(queryVector: List<Float>): List<Map<String, Any>> = emptyList()
    override fun advancedSearch(payload: Map<String, Any>): Map<String, Any> = mapOf("ok" to true)
    override fun getReviewQueue(): List<Map<String, Any>> = emptyList()
    override fun updateReview(itemId: String, action: String, payload: Map<String, Any>): Boolean = true
    override fun listKnowledgePacks(): List<Map<String, Any>> = emptyList()
    override fun listDownloads(): List<Map<String, Any>> = emptyList()
    override fun listPlugins(): List<Map<String, Any>> = emptyList()
}
