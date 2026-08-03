package com.ailm.android.runtime

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File

object StandaloneRuntime {
    private val imageExtensions = setOf(
        "png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff", "avif", "heif", "heic",
    )

    private val stateMutex = Mutex()
    private val runtimeScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @Volatile
    private var initialized = false
    private lateinit var storageProvider: StorageProvider
    private lateinit var repository: LocalRepository
    private lateinit var appContext: Context

    private var scanStatus: String = "idle"
    private var scanRoot: String? = null
    private var scanProgress: Double = 0.0
    private var scanDiscovered: Int = 0
    private var scanCurrentFile: String? = null
    private var scanError: String? = null
    private var scanPaused: Boolean = false
    private var scanCancelled: Boolean = false

    fun initialize(context: Context) {
        if (initialized) {
            return
        }
        runBlocking {
            stateMutex.withLock {
                if (!initialized) {
                    appContext = context.applicationContext
                    storageProvider = SafStorageProvider(context.applicationContext)
                    repository = LocalRepository(LocalDatabase(context.applicationContext))
                    initialized = true
                }
            }
        }
    }

    fun healthStatus(): Map<String, Any> {
        ensureInitialized()
        return mapOf(
            "status" to "ok",
            "mode" to "android-standalone",
        )
    }

    fun libraryStatistics(): Map<String, Any> {
        ensureInitialized()
        val stats = repository.statistics()
        val status = runBlocking {
            stateMutex.withLock { scanStatus }
        }
        return mapOf(
            "total_images" to (stats["total_images"] ?: 0),
            "total_size_bytes" to (stats["total_size_bytes"] ?: 0L),
            "scan_status" to status,
        )
    }

    fun startScan(root: String): Map<String, Any> {
        ensureInitialized()
        val rootUri = root.trim()
        require(rootUri.isNotBlank()) { "scan root is required" }

        val existingStatus = runBlocking {
            stateMutex.withLock {
                if (scanStatus == "running" || scanStatus == "paused") {
                    snapshotStatus()
                } else {
                    scanStatus = "running"
                    scanRoot = rootUri
                    scanProgress = 0.0
                    scanDiscovered = 0
                    scanCurrentFile = null
                    scanError = null
                    scanPaused = false
                    scanCancelled = false
                    null
                }
            }
        }
        if (existingStatus != null) {
            return existingStatus
        }

        runtimeScope.launch {
            try {
                if (!storageProvider.exists(rootUri)) {
                    throw IllegalStateException("Selected SAF root is no longer available: $rootUri")
                }
                val scannedAt = System.currentTimeMillis()
                for (node in storageProvider.walkTree(rootUri)) {
                    val shouldContinue = awaitRunningState()
                    if (!shouldContinue) {
                        stateMutex.withLock {
                            scanStatus = "cancelled"
                            scanProgress = 0.0
                        }
                        return@launch
                    }
                    if (node.isDirectory || !node.name.isImageName()) {
                        continue
                    }
                    repository.upsertImage(node, scannedAt)
                    stateMutex.withLock {
                        scanDiscovered += 1
                        scanCurrentFile = node.uri
                        scanProgress = if (scanDiscovered < 1) 0.0 else 50.0
                    }
                }
                stateMutex.withLock {
                    scanStatus = "completed"
                    scanProgress = 100.0
                }
            } catch (t: Throwable) {
                stateMutex.withLock {
                    scanStatus = "failed"
                    scanError = t.message ?: t.javaClass.simpleName
                    scanProgress = 0.0
                }
            }
        }

        return runBlocking {
            stateMutex.withLock { snapshotStatus() }
        }
    }

    fun scanStatus(): Map<String, Any> {
        ensureInitialized()
        return runBlocking {
            stateMutex.withLock { snapshotStatus() }
        }
    }

    fun pauseScan(): Boolean {
        ensureInitialized()
        return runBlocking {
            stateMutex.withLock {
                if (scanStatus != "running") {
                    return@withLock false
                }
                scanPaused = true
                scanStatus = "paused"
                true
            }
        }
    }

    fun resumeScan(): Boolean {
        ensureInitialized()
        return runBlocking {
            stateMutex.withLock {
                if (scanStatus != "paused") {
                    return@withLock false
                }
                scanPaused = false
                scanStatus = "running"
                true
            }
        }
    }

    fun cancelScan(): Boolean {
        ensureInitialized()
        return runBlocking {
            stateMutex.withLock {
                if (scanStatus !in setOf("running", "paused")) {
                    return@withLock false
                }
                scanCancelled = true
                scanPaused = false
                scanStatus = "cancelled"
                true
            }
        }
    }

    fun getCollections(query: String? = null, page: Int = 1, pageSize: Int = 50): List<Map<String, Any>> {
        ensureInitialized()
        val items = repository.collections(page = page, pageSize = pageSize)
        if (query.isNullOrBlank()) {
            return items
        }
        val term = query.trim().lowercase()
        return items.filter { (it["name"]?.toString() ?: "").lowercase().contains(term) }
    }

    fun getLibraryImages(query: String? = null, page: Int = 1, pageSize: Int = 200): List<Map<String, Any>> {
        ensureInitialized()
        return repository.listImages(query = query, page = page, pageSize = pageSize)
    }

    fun getTags(): List<String> {
        ensureInitialized()
        return repository.listImages(query = null, page = 1, pageSize = 500)
            .mapNotNull { it["filename"]?.toString() }
            .flatMap { name ->
                name.split('_', '-', ' ').map { it.trim().lowercase() }.filter { it.length > 2 }
            }
            .groupingBy { it }
            .eachCount()
            .entries
            .sortedByDescending { it.value }
            .take(100)
            .map { it.key }
    }

    fun searchByFilename(query: String): List<Map<String, Any>> {
        ensureInitialized()
        return repository.listImages(query = query, page = 1, pageSize = 200)
    }

    fun semanticSearch(queryVector: List<Float>): List<Map<String, Any>> {
        ensureInitialized()
        return repository.listImages(query = null, page = 1, pageSize = 200)
    }

    fun advancedSearch(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val query = payload["query"]?.toString()
        val items = repository.listImages(query = query, page = 1, pageSize = 200)
        return mapOf("ok" to true, "items" to items, "count" to items.size)
    }

    fun getReviewQueue(): List<Map<String, Any>> {
        ensureInitialized()
        return repository.reviewQueue()
    }

    fun updateReview(itemId: String, action: String, payload: Map<String, Any> = emptyMap()): Boolean {
        ensureInitialized()
        val normalizedItem = itemId.trim()
        val normalizedAction = action.trim().lowercase()
        if (normalizedItem.isBlank() || normalizedAction.isBlank()) {
            return false
        }
        if (normalizedAction == "undo") {
            return repository.undoLastReviewUpdate()
        }
        val reason = payload["reason"]?.toString()
        return repository.updateReview(normalizedItem, normalizedAction, reason)
    }

    fun listKnowledgePacks(): List<Map<String, Any>> {
        ensureInitialized()
        val dir = File(appContext.filesDir, "knowledge_packs")
        return listLocalArtifacts(dir, kind = "knowledge_pack")
    }

    fun listDownloads(): List<Map<String, Any>> {
        ensureInitialized()
        val dir = File(appContext.filesDir, "downloads")
        return listLocalArtifacts(dir, kind = "download")
    }

    fun listPlugins(): List<Map<String, Any>> {
        ensureInitialized()
        val dir = File(appContext.filesDir, "plugins")
        return listLocalArtifacts(dir, kind = "plugin")
    }

    private fun ensureInitialized() {
        check(initialized) { "StandaloneRuntime is not initialized" }
    }

    private suspend fun awaitRunningState(): Boolean {
        while (true) {
            val (paused, cancelled) = stateMutex.withLock {
                scanPaused to scanCancelled
            }
            if (cancelled) {
                return false
            }
            if (!paused) {
                return true
            }
            delay(50)
        }
    }

    private fun snapshotStatus(): Map<String, Any> {
        return mapOf(
            "status" to scanStatus,
            "root" to (scanRoot ?: ""),
            "discovered_images" to scanDiscovered,
            "current_file" to (scanCurrentFile ?: ""),
            "job_id" to "scan-library",
            "error" to (scanError ?: ""),
            "progress" to scanProgress,
        )
    }

    private fun String.isImageName(): Boolean {
        val idx = lastIndexOf('.')
        if (idx < 0 || idx == lastIndex) {
            return false
        }
        val ext = substring(idx + 1).lowercase()
        return ext in imageExtensions
    }

    private fun listLocalArtifacts(directory: File, kind: String): List<Map<String, Any>> {
        if (!directory.exists()) {
            return emptyList()
        }
        val files = directory.listFiles()?.sortedBy { it.name.lowercase() } ?: return emptyList()
        return files.map {
            mapOf(
                "type" to kind,
                "name" to it.name,
                "path" to it.absolutePath,
                "exists" to it.exists(),
                "size_bytes" to it.length(),
                "last_modified_ms" to it.lastModified(),
            )
        }
    }
}
