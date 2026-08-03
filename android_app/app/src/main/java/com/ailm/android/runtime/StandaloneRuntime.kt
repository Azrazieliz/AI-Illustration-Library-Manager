package com.ailm.android.runtime

import android.content.Context
import android.graphics.BitmapFactory
import android.util.Log
import com.ailm.android.runtime.ai.LocalAiManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File
import java.util.UUID

object StandaloneRuntime {
    private const val RUNTIME_TRACE_TAG = "AilmTraceRuntime"

    private val imageExtensions = setOf(
        "png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff", "avif", "heif", "heic",
    )

    private val stateMutex = Mutex()
    private val runtimeScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @Volatile
    private var initialized = false
    private lateinit var storageProvider: StorageProvider
    private lateinit var repository: LocalRepository
    private lateinit var localAiManager: LocalAiManager
    private lateinit var appContext: Context

    private var scanStatus: String = "idle"
    private var scanRoot: String? = null
    private var scanProgress: Double = 0.0
    private var scanDiscovered: Int = 0
    private var scanCurrentFile: String? = null
    private var scanError: String? = null
    private var scanPaused: Boolean = false
    private var scanCancelled: Boolean = false
    private var scanSkipped: Int = 0
    private var lastUndoOperations: List<FileOperationPlan> = emptyList()

    private data class FileOperationPlan(
        val action: String,
        val imageId: Int? = null,
        val sourceUri: String = "",
        val sourceName: String = "",
        val sourceFolderUri: String = "",
        val targetFolderUri: String = "",
        val targetName: String = "",
        val conflictMode: String = "rename",
        val canUndo: Boolean = true,
    )

    private class OperationConflictResolver(
        private val storageProvider: StorageProvider,
    ) {
        private val namesByFolder = mutableMapOf<String, MutableSet<String>>()

        fun hasConflict(folderUri: String, targetName: String): Boolean {
            val clean = targetName.trim()
            if (clean.isBlank() || folderUri.isBlank()) {
                return false
            }
            return folderNames(folderUri).contains(clean.lowercase())
        }

        fun reserve(folderUri: String, targetName: String) {
            val clean = targetName.trim()
            if (clean.isBlank() || folderUri.isBlank()) {
                return
            }
            folderNames(folderUri) += clean.lowercase()
        }

        private fun folderNames(folderUri: String): MutableSet<String> {
            return namesByFolder.getOrPut(folderUri) {
                storageProvider.listChildren(folderUri).map { it.name.lowercase() }.toMutableSet()
            }
        }
    }

    fun initialize(context: Context) {
        if (initialized) {
            return
        }
        runBlocking {
            stateMutex.withLock {
                if (!initialized) {
                    appContext = context.applicationContext
                    storageProvider = SafStorageProvider(context.applicationContext)
                    val localDatabase = LocalDatabase(context.applicationContext)
                    repository = LocalRepository(localDatabase)
                    localAiManager = LocalAiManager(
                        context = context.applicationContext,
                        database = localDatabase,
                        scope = runtimeScope,
                    )
                    localAiManager.initialize()
                    cleanupLegacySettings()
                    repository.optimizeDatabase()
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
        val scanRuns = repository.scanStatistics(limit = 20)
        val folders = repository.listFolders(includeDisabled = true)
        return mapOf(
            "total_images" to (stats["total_images"] ?: 0),
            "total_size_bytes" to (stats["total_size_bytes"] ?: 0L),
            "total_favorites" to (stats["total_favorites"] ?: 0),
            "avg_rating" to (stats["avg_rating"] ?: 0.0),
            "total_folders" to folders.size,
            "scan_status" to status,
            "recent_scans" to scanRuns,
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
                    scanSkipped = 0
                    null
                }
            }
        }
        if (existingStatus != null) {
            return existingStatus
        }

        runtimeScope.launch {
            val scanStartedAt = System.currentTimeMillis()
            val scanId = repository.beginScanRun(rootUri, scanStartedAt)
            repository.registerFolder(rootUri, enabled = true)
            try {
                if (!storageProvider.exists(rootUri)) {
                    throw IllegalStateException("Selected SAF root is no longer available: $rootUri")
                }
                val scannedAt = scanStartedAt
                var importIndex = 0L
                var discoveredLocal = 0
                var skippedLocal = 0
                for (node in storageProvider.walkTree(rootUri)) {
                    val shouldContinue = awaitRunningState()
                    if (!shouldContinue) {
                        stateMutex.withLock {
                            scanStatus = "cancelled"
                            scanProgress = 0.0
                        }
                        repository.finishScanRun(
                            scanId = scanId,
                            folderUri = rootUri,
                            completedAtMs = System.currentTimeMillis(),
                            status = "cancelled",
                            discoveredCount = discoveredLocal,
                            skippedCount = skippedLocal,
                            errorMessage = "cancelled",
                        )
                        return@launch
                    }
                    if (node.isDirectory || !node.name.isImageName()) {
                        skippedLocal += 1
                        continue
                    }

                    importIndex += 1
                    val metadata = extractMetadata(node)
                    repository.upsertImage(
                        node = node,
                        folderUri = rootUri,
                        scannedAtMs = scannedAt,
                        importOrder = scannedAt * 1_000_000L + importIndex,
                        metadata = metadata,
                        metadataText = buildMetadataText(node, metadata),
                    )
                    discoveredLocal += 1

                    stateMutex.withLock {
                        scanDiscovered += 1
                        scanSkipped = skippedLocal
                        scanCurrentFile = node.uri
                        scanProgress = if (scanDiscovered < 1) 0.0 else minOf(99.0, 5.0 + (scanDiscovered * 0.5))
                    }
                }

                repository.markFolderImagesInactiveBefore(rootUri, scannedAt)
                repository.rebuildSearchIndex()
                repository.optimizeDatabase()

                stateMutex.withLock {
                    scanStatus = "completed"
                    scanProgress = 100.0
                }
                repository.finishScanRun(
                    scanId = scanId,
                    folderUri = rootUri,
                    completedAtMs = System.currentTimeMillis(),
                    status = "completed",
                    discoveredCount = discoveredLocal,
                    skippedCount = skippedLocal,
                    errorMessage = null,
                )
            } catch (t: Throwable) {
                stateMutex.withLock {
                    scanStatus = "failed"
                    scanError = t.message ?: t.javaClass.simpleName
                    scanProgress = 0.0
                }
                repository.finishScanRun(
                    scanId = scanId,
                    folderUri = rootUri,
                    completedAtMs = System.currentTimeMillis(),
                    status = "failed",
                    discoveredCount = scanDiscovered,
                    skippedCount = scanSkipped,
                    errorMessage = t.message ?: t.javaClass.simpleName,
                )
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

    fun getLibraryImages(query: String? = null, page: Int = 1, pageSize: Int = 0): List<Map<String, Any>> {
        ensureInitialized()
        return repository.searchImages(
            LibraryQueryOptions(
                query = query,
                page = page,
                pageSize = pageSize,
                sortBy = "import_order",
                sortDirection = "desc",
            ),
        )
    }

    fun getTags(): List<String> {
        ensureInitialized()
        return repository.listStoredTags(limit = 5000)
    }

    fun searchByFilename(query: String): List<Map<String, Any>> {
        ensureInitialized()
        return repository.searchImages(
            LibraryQueryOptions(
                query = query,
                page = 1,
                pageSize = 0,
                sortBy = "filename",
                sortDirection = "asc",
            ),
        )
    }

    fun searchByImageId(imageId: Int): Map<String, Any>? {
        ensureInitialized()
        val result = repository.searchByImageId(imageId)
        Log.d(RUNTIME_TRACE_TAG, "Runtime returned object: imageId=$imageId ${imageSummary(result)}")
        return result
    }

    fun semanticSearch(queryVector: List<Float>): List<Map<String, Any>> {
        return semanticSearch(queryVector, emptyMap())
    }

    fun semanticSearch(queryVector: List<Float>, payload: Map<String, Any> = emptyMap()): List<Map<String, Any>> {
        ensureInitialized()
        val baseOptions = payload.toQueryOptions().copy(
            query = null,
            fullText = null,
            sortBy = "import_order",
            sortDirection = "desc",
            page = 1,
            pageSize = 0,
        )
        val candidateLimit = payload["candidate_limit"].toIntOrNullValue()?.coerceIn(1, 2_000) ?: 600
        val candidateRows = repository.searchImages(baseOptions).take(candidateLimit)
        if (candidateRows.isEmpty()) {
            return emptyList()
        }

        val topK = payload["top_k"].toIntOrNullValue()?.coerceAtLeast(1) ?: minOf(200, candidateRows.size)
        val semanticPayload = linkedMapOf<String, Any>(
            "query" to payload["query"]?.toString()?.trim().orEmpty(),
            "top_k" to topK,
            "candidates" to candidateRows.mapNotNull { row -> row.toSemanticCandidatePayloadOrNull() },
        )
        if (queryVector.isNotEmpty()) {
            semanticPayload["query_embedding"] = queryVector.map { it.toDouble() }
        }

        val response = localAiManager.semanticSearch(semanticPayload)
        val matches = extractSemanticMatches(response)
        if (matches.isEmpty()) {
            return candidateRows.take(topK)
        }

        val rowsById = candidateRows.mapNotNull { row ->
            val imageId = row["image_id"].toIntOrNullValue() ?: return@mapNotNull null
            imageId to row
        }.toMap()

        val ranked = mutableListOf<Map<String, Any>>()
        matches.forEachIndexed { index, match ->
            val imageId = match["image_id"].toIntOrNullValue() ?: return@forEachIndexed
            val source = rowsById[imageId] ?: repository.searchByImageId(imageId) ?: return@forEachIndexed
            val enriched = source.toMutableMap()
            match["score"].toDoubleOrNullValue()?.let { score ->
                enriched["semantic_score"] = score
            }
            enriched["semantic_rank"] = index + 1
            ranked += enriched
        }

        return if (ranked.isEmpty()) candidateRows.take(topK) else ranked
    }

    fun advancedSearch(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val options = payload.toQueryOptions()
        val items = repository.searchImages(options)
        val total = repository.countImages(options)
        return mapOf(
            "ok" to true,
            "items" to items,
            "count" to total,
            "sort_by" to options.sortBy,
            "sort_direction" to options.sortDirection,
        )
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

    fun localAiOverview(): Map<String, Any> {
        ensureInitialized()
        return localAiManager.overview()
    }

    fun localAiExecutionChain(): Map<String, Any> {
        ensureInitialized()
        return localAiManager.executionChain()
    }

    fun detectAiHardwareProfile(): Map<String, Any> {
        ensureInitialized()
        return localAiManager.detectHardwareProfile()
    }

    fun latestAiHardwareProfile(): Map<String, Any> {
        ensureInitialized()
        return localAiManager.latestHardwareProfile()
    }

    fun listAiBackends(): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listBackends()
    }

    fun registerAvailableAiModel(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.registerAvailableModel(payload)
    }

    fun listAvailableAiModels(): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listAvailableModels()
    }

    fun listInstalledAiModels(): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listInstalledModels()
    }

    fun importLocalAiModel(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.importLocalModel(payload)
    }

    fun registerAiModelDownload(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.registerModelDownload(payload)
    }

    fun verifyInstalledAiModel(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.verifyInstalledModel(payload)
    }

    fun removeAiModel(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.removeModel(payload)
    }

    fun detectAiModelUpdates(): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.detectModelUpdates()
    }

    fun enqueueAiTask(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.enqueueTask(payload)
    }

    fun cancelAiTask(taskId: String): Boolean {
        ensureInitialized()
        return localAiManager.cancelTask(taskId.trim())
    }

    fun pauseAiTask(taskId: String): Boolean {
        ensureInitialized()
        return localAiManager.pauseTask(taskId.trim())
    }

    fun resumeAiTask(taskId: String): Boolean {
        ensureInitialized()
        return localAiManager.resumeTask(taskId.trim())
    }

    fun retryAiTask(taskId: String): Boolean {
        ensureInitialized()
        return localAiManager.retryTask(taskId.trim())
    }

    fun listAiTasks(limit: Int = 200): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listTasks(limit)
    }

    fun resumeAiQueue(): Boolean {
        ensureInitialized()
        localAiManager.resumeQueue()
        return true
    }

    fun pauseAiQueue(): Boolean {
        ensureInitialized()
        localAiManager.pauseQueue()
        return true
    }

    fun listAiInstallRuns(limit: Int = 100): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listInstallRuns(limit)
    }

    fun listAiExecutionSessions(limit: Int = 200): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listExecutionSessions(limit)
    }

    fun listAiExecutionEvents(sessionId: String, limit: Int = 500): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listExecutionEvents(sessionId.trim(), limit)
    }

    fun listAiRuntimeHealthSnapshots(limit: Int = 200): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listRuntimeHealthSnapshots(limit)
    }

    fun aiSettings(): Map<String, Any> {
        ensureInitialized()
        return localAiManager.getSettings()
    }

    fun updateAiSettings(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.updateSettings(payload)
    }

    fun listAiPlugins(enabledOnly: Boolean? = null): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listPlugins(enabledOnly)
    }

    fun registerAiPlugin(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.registerPlugin(payload)
    }

    fun listAiCapabilities(providerId: String = ""): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listCapabilities(providerId)
    }

    fun registerAiCapability(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.registerCapability(payload)
    }

    fun listAiCacheEntries(limit: Int = 200): List<Map<String, Any>> {
        ensureInitialized()
        return localAiManager.listCacheEntries(limit)
    }

    fun upsertAiCacheEntry(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return localAiManager.upsertCacheEntry(payload)
    }

    fun pruneAiCache(): Map<String, Any> {
        ensureInitialized()
        return localAiManager.pruneCache()
    }

    fun validateLocalAiInfrastructure(): Map<String, Any> {
        ensureInitialized()
        return localAiManager.validateInfrastructure()
    }

    fun runAiPipeline(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val prepared = prepareAiPipelinePayload(payload)
        val response = localAiManager.runPipeline(prepared)
        applyPipelineSideEffects(prepared, response)
        return response
    }

    fun runAiBatchPipeline(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val rawItems = (payload["items"] as? List<*>)
            ?.mapNotNull { (it as? Map<*, *>)?.toStringAnyMap() }
            ?: emptyList()
        if (rawItems.isEmpty()) {
            return mapOf("ok" to false, "status" to "invalid", "message" to "items are required")
        }

        val preparedItems = rawItems.map { prepareAiPipelinePayload(it) }
        val batchPayload = linkedMapOf<String, Any>()
        batchPayload.putAll(payload)
        batchPayload["items"] = preparedItems

        val response = localAiManager.runBatchPipeline(batchPayload)
        val responseItems = (response["items"] as? List<*>)
            ?.mapNotNull { (it as? Map<*, *>)?.toStringAnyMap() }
            ?: emptyList()
        preparedItems.forEachIndexed { index, prepared ->
            val item = responseItems.getOrNull(index) ?: return@forEachIndexed
            val itemResult = (item["result"] as? Map<*, *>)?.toStringAnyMap() ?: return@forEachIndexed
            applyPipelineSideEffects(prepared, itemResult)
        }
        return response
    }

    fun runMultiStageAiPipeline(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val prepared = prepareAiPipelinePayload(payload)
        val response = localAiManager.runMultiStagePipeline(prepared)
        applyPipelineSideEffects(prepared, response)
        return response
    }

    fun runKnowledgePackExecution(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val prepared = prepareAiPipelinePayload(payload + mapOf("task_type" to "knowledge_pack_execution"))
        val response = localAiManager.executeKnowledgePack(prepared)
        applyPipelineSideEffects(prepared, response)
        return response
    }

    fun runOcrPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "ocr"))
    }

    fun runCaptioningPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "captioning"))
    }

    fun runCharacterRecognitionPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "character_recognition"))
    }

    fun runSeriesRecognitionPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "series_recognition"))
    }

    fun runArtistRecognitionPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "artist_recognition"))
    }

    fun runTagPredictionPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "tag_prediction"))
    }

    fun runMetadataExtractionPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "metadata_extraction"))
    }

    fun runPromptGenerationPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "prompt_generation"))
    }

    fun runEmbeddingGenerationPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "embedding_generation"))
    }

    fun runDuplicateDetectionPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "duplicate_detection"))
    }

    fun runClassificationPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "classification"))
    }

    fun runDetectionPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "detection"))
    }

    fun runFaceFeatureExtractionPipeline(payload: Map<String, Any>): Map<String, Any> {
        return runAiPipeline(payload + mapOf("task_type" to "face_feature_extraction"))
    }

    fun listLibraryFolders(includeDisabled: Boolean = true): List<Map<String, Any>> {
        ensureInitialized()
        return repository.listFolders(includeDisabled = includeDisabled)
    }

    fun addLibraryFolder(folderUri: String): Boolean {
        ensureInitialized()
        val uri = folderUri.trim()
        if (uri.isBlank()) {
            return false
        }
        repository.registerFolder(uri, enabled = true)
        return true
    }

    fun setLibraryFolderEnabled(folderUri: String, enabled: Boolean): Boolean {
        ensureInitialized()
        return repository.setFolderEnabled(folderUri, enabled)
    }

    fun removeLibraryFolder(folderUri: String): Boolean {
        ensureInitialized()
        return repository.removeFolder(folderUri)
    }

    fun rescanFolder(folderUri: String): Map<String, Any> {
        ensureInitialized()
        return startScan(folderUri)
    }

    fun rescanEnabledFolders(): List<Map<String, Any>> {
        ensureInitialized()
        val folders = repository.listFolders(includeDisabled = false)
        val responses = mutableListOf<Map<String, Any>>()
        for (folder in folders) {
            val uri = folder["folder_uri"]?.toString().orEmpty()
            if (uri.isBlank()) {
                continue
            }
            responses += startScan(uri)
        }
        return responses
    }

    fun setImageFavorite(imageId: Int, favorite: Boolean): Boolean {
        ensureInitialized()
        Log.d(RUNTIME_TRACE_TAG, "Runtime receives favorite: imageId=$imageId nextFavorite=$favorite")
        val ok = repository.setFavorite(imageId, favorite)
        Log.d(RUNTIME_TRACE_TAG, "Runtime entry after repository call (favorite): imageId=$imageId ok=$ok")
        Log.d(RUNTIME_TRACE_TAG, "Runtime favorite update result: imageId=$imageId ok=$ok")
        return ok
    }

    fun setImageRating(imageId: Int, rating: Int): Boolean {
        ensureInitialized()
        Log.d(RUNTIME_TRACE_TAG, "Runtime receives rating: imageId=$imageId nextRating=$rating")
        val ok = repository.setRating(imageId, rating)
        Log.d(RUNTIME_TRACE_TAG, "Runtime entry after repository call (rating): imageId=$imageId ok=$ok")
        Log.d(RUNTIME_TRACE_TAG, "Runtime rating update result: imageId=$imageId ok=$ok")
        return ok
    }

    fun setImageTags(imageId: Int, tags: List<String>): Boolean {
        ensureInitialized()
        Log.d(RUNTIME_TRACE_TAG, "Runtime receives tags: imageId=$imageId nextTags=${tags.joinToString("|")}")
        val ok = repository.setTags(imageId, tags)
        Log.d(RUNTIME_TRACE_TAG, "Runtime entry after repository call (tags): imageId=$imageId ok=$ok")
        Log.d(RUNTIME_TRACE_TAG, "Runtime tags update result: imageId=$imageId ok=$ok")
        return ok
    }

    fun scanStatistics(limit: Int = 20): List<Map<String, Any>> {
        ensureInitialized()
        return repository.scanStatistics(limit)
    }

    fun rebuildSearchIndex(): Boolean {
        ensureInitialized()
        repository.rebuildSearchIndex()
        return true
    }

    fun optimizeDatabase(): Boolean {
        ensureInitialized()
        repository.optimizeDatabase()
        return true
    }

    fun manageThumbnailCache(maxBytes: Long = 256L * 1024L * 1024L): Map<String, Any> {
        ensureInitialized()
        val cacheDir = File(appContext.cacheDir, "thumbnails")
        cacheDir.mkdirs()
        return repository.pruneThumbnailCache(maxBytes, cacheDir)
    }

    fun updateSetting(key: String, value: String): Boolean {
        ensureInitialized()
        if (key.isBlank()) {
            return false
        }
        repository.setSetting(key.trim(), value)
        return true
    }

    fun getSetting(key: String, defaultValue: String = ""): String {
        ensureInitialized()
        return repository.getSetting(key.trim(), defaultValue)
    }

    fun exportFusionDatabase(format: String = "json", pretty: Boolean = true): String {
        ensureInitialized()
        val parsedFormat = parseFusionImportFormat(format)
        return repository.exportFusionDatabase(parsedFormat, pretty = pretty)
    }

    fun importFusionDatabase(
        payload: String,
        format: String = "json",
        replaceExisting: Boolean = false,
    ): Map<String, Any> {
        ensureInitialized()
        val parsedFormat = parseFusionImportFormat(format)
        val result = repository.importFusionDatabase(
            payload = payload,
            format = parsedFormat,
            replaceExisting = replaceExisting,
        )
        return result.toMap()
    }

    fun previewImport(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val request = payload.toExternalImportRequest()
        val preview = repository.previewImport(request)
        return mapOf(
            "ok" to true,
            "preview" to preview.toMap(),
        )
    }

    fun importDatabase(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val request = payload.toExternalImportRequest()
        val result = repository.importDatabase(request)
        return result.toMap()
    }

    fun cancelImport(importId: String): Boolean {
        ensureInitialized()
        return repository.cancelImport(importId.trim())
    }

    fun rollbackImport(importId: String? = null): Map<String, Any> {
        ensureInitialized()
        val result = repository.rollbackImport(importId?.trim()?.ifBlank { null })
        return result.toMap()
    }

    fun validateImport(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val request = payload.toExternalImportRequest()
        val report = repository.validateImport(request)
        return mapOf(
            "ok" to report.valid,
            "import_id" to request.importId,
            "validation" to report.toMap(),
        )
    }

    fun validateFusionDatabase(): Map<String, Any> {
        ensureInitialized()
        return repository.validateFusionDatabase(persistRun = true).toMap()
    }

    fun previewFileOperations(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return buildFileOperationPreview(payload, includeConflictAnalysis = true)
    }

    fun executeFileOperations(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val planBuild = buildFileOperationPlans(payload)
        if (!planBuild.ok) {
            return mapOf("ok" to false, "message" to planBuild.message)
        }

        val plans = planBuild.plans
        val results = mutableListOf<Map<String, Any>>()
        val undo = mutableListOf<FileOperationPlan>()
        val touchedFolders = mutableSetOf<String>()
        val recordsById = repository.getImageRecordsByIds(
            plans.mapNotNull { it.imageId }.distinct(),
        ).associateBy { it.imageId }
        val total = plans.size.coerceAtLeast(1)
        var executed = 0

        for (plan in plans) {
            val result = executePlan(plan, recordsById)
            executed += 1
            results += result + mapOf("progress" to (executed.toDouble() / total.toDouble()))

            if (result["ok"] == true) {
                touchedFolders += plan.sourceFolderUri
                touchedFolders += plan.targetFolderUri
                inversePlan(plan, result)?.let { undo += it }
            }
        }

        lastUndoOperations = undo

        return mapOf(
            "ok" to true,
            "results" to results,
            "executed" to executed,
            "total" to plans.size,
            "undo_available" to undo.isNotEmpty(),
            "touched_folders" to touchedFolders.filter { it.isNotBlank() },
        )
    }

    fun undoLastFileOperations(): Map<String, Any> {
        ensureInitialized()
        if (lastUndoOperations.isEmpty()) {
            return mapOf("ok" to false, "message" to "No undo operation available.")
        }
        val results = mutableListOf<Map<String, Any>>()
        val plans = lastUndoOperations.asReversed()
        val recordsById = repository.getImageRecordsByIds(
            plans.mapNotNull { it.imageId }.distinct(),
        ).associateBy { it.imageId }
        for (plan in plans) {
            results += executePlan(plan, recordsById)
        }
        lastUndoOperations = emptyList()
        return mapOf(
            "ok" to true,
            "results" to results,
            "executed" to results.size,
        )
    }

    private data class PlanBuildResult(
        val ok: Boolean,
        val message: String = "",
        val plans: List<FileOperationPlan> = emptyList(),
    )

    private fun buildFileOperationPlans(payload: Map<String, Any>): PlanBuildResult {
        val action = payload["action"]?.toString()?.trim()?.lowercase().orEmpty()
        if (action.isBlank()) {
            return PlanBuildResult(ok = false, message = "action is required")
        }

        val imageIds = parseImageIds(payload["image_ids"])
        val records = repository.getImageRecordsByIds(imageIds)
        val recordsById = records.associateBy { it.imageId }
        val targetFolderUri = payload["target_folder_uri"]?.toString()?.trim().orEmpty()
        val sourceFolderUri = payload["source_folder_uri"]?.toString()?.trim().orEmpty()
        val singleName = payload["name"]?.toString()?.trim().orEmpty()
        val pattern = payload["pattern"]?.toString()?.trim().orEmpty()
        val folderName = payload["folder_name"]?.toString()?.trim().orEmpty()
        val conflictMode = payload["conflict_mode"]?.toString()?.trim()?.lowercase().orEmpty().ifBlank { "rename" }

        val plans = mutableListOf<FileOperationPlan>()
        when (action) {
            "rename_image" -> {
                val id = imageIds.firstOrNull() ?: return PlanBuildResult(ok = false, message = "image_id is required")
                val record = recordsById[id] ?: return PlanBuildResult(ok = false, message = "image not found: $id")
                if (singleName.isBlank()) {
                    return PlanBuildResult(ok = false, message = "name is required")
                }
                plans += FileOperationPlan(
                    action = action,
                    imageId = id,
                    sourceUri = record.uri,
                    sourceName = record.filename,
                    sourceFolderUri = record.folderUri,
                    targetFolderUri = record.folderUri,
                    targetName = singleName,
                    conflictMode = conflictMode,
                )
            }
            "batch_rename_images" -> {
                if (imageIds.isEmpty()) {
                    return PlanBuildResult(ok = false, message = "image_ids are required")
                }
                if (pattern.isBlank()) {
                    return PlanBuildResult(ok = false, message = "pattern is required")
                }
                imageIds.forEachIndexed { index, id ->
                    val record = recordsById[id] ?: return@forEachIndexed
                    plans += FileOperationPlan(
                        action = action,
                        imageId = id,
                        sourceUri = record.uri,
                        sourceName = record.filename,
                        sourceFolderUri = record.folderUri,
                        targetFolderUri = record.folderUri,
                        targetName = pattern.replace("{n}", (index + 1).toString()),
                        conflictMode = conflictMode,
                    )
                }
            }
            "rename_folder" -> {
                if (sourceFolderUri.isBlank() || folderName.isBlank()) {
                    return PlanBuildResult(ok = false, message = "source_folder_uri and folder_name are required")
                }
                plans += FileOperationPlan(
                    action = action,
                    sourceUri = sourceFolderUri,
                    sourceFolderUri = sourceFolderUri,
                    targetName = folderName,
                    canUndo = true,
                )
            }
            "create_folder" -> {
                if (targetFolderUri.isBlank() || folderName.isBlank()) {
                    return PlanBuildResult(ok = false, message = "target_folder_uri and folder_name are required")
                }
                plans += FileOperationPlan(
                    action = action,
                    sourceFolderUri = targetFolderUri,
                    targetFolderUri = targetFolderUri,
                    targetName = folderName,
                    canUndo = true,
                )
            }
            "delete_folder" -> {
                if (sourceFolderUri.isBlank()) {
                    return PlanBuildResult(ok = false, message = "source_folder_uri is required")
                }
                plans += FileOperationPlan(
                    action = action,
                    sourceUri = sourceFolderUri,
                    sourceFolderUri = sourceFolderUri,
                    canUndo = false,
                )
            }
            "delete_images", "batch_delete" -> {
                if (imageIds.isEmpty()) {
                    return PlanBuildResult(ok = false, message = "image_ids are required")
                }
                imageIds.forEach { id ->
                    val record = recordsById[id] ?: return@forEach
                    plans += FileOperationPlan(
                        action = "delete_images",
                        imageId = id,
                        sourceUri = record.uri,
                        sourceName = record.filename,
                        sourceFolderUri = record.folderUri,
                        canUndo = false,
                    )
                }
            }
            "move_images", "batch_move" -> {
                if (imageIds.isEmpty() || targetFolderUri.isBlank()) {
                    return PlanBuildResult(ok = false, message = "image_ids and target_folder_uri are required")
                }
                imageIds.forEach { id ->
                    val record = recordsById[id] ?: return@forEach
                    plans += FileOperationPlan(
                        action = "move_images",
                        imageId = id,
                        sourceUri = record.uri,
                        sourceName = record.filename,
                        sourceFolderUri = record.folderUri,
                        targetFolderUri = targetFolderUri,
                        targetName = record.filename,
                        conflictMode = conflictMode,
                    )
                }
            }
            "copy_images", "batch_copy" -> {
                if (imageIds.isEmpty() || targetFolderUri.isBlank()) {
                    return PlanBuildResult(ok = false, message = "image_ids and target_folder_uri are required")
                }
                imageIds.forEach { id ->
                    val record = recordsById[id] ?: return@forEach
                    plans += FileOperationPlan(
                        action = "copy_images",
                        imageId = id,
                        sourceUri = record.uri,
                        sourceName = record.filename,
                        sourceFolderUri = record.folderUri,
                        targetFolderUri = targetFolderUri,
                        targetName = record.filename,
                        conflictMode = conflictMode,
                    )
                }
            }
            else -> return PlanBuildResult(ok = false, message = "unsupported action: $action")
        }

        return PlanBuildResult(ok = true, plans = plans)
    }

    private fun buildFileOperationPreview(
        payload: Map<String, Any>,
        includeConflictAnalysis: Boolean,
    ): Map<String, Any> {
        val planBuild = buildFileOperationPlans(payload)
        if (!planBuild.ok) {
            return mapOf("ok" to false, "message" to planBuild.message)
        }

        val plans = planBuild.plans
        val previewRows = mutableListOf<Map<String, Any>>()

        val previewConflictResolver = if (includeConflictAnalysis) OperationConflictResolver(storageProvider) else null
        plans.forEachIndexed { index, plan ->
            val targetName = plan.targetName
            val conflict = if (includeConflictAnalysis) {
                val folder = if (plan.targetFolderUri.isBlank()) plan.sourceFolderUri else plan.targetFolderUri
                val resolver = previewConflictResolver ?: return@forEachIndexed
                val hasConflict = resolver.hasConflict(folder, targetName)
                if (!hasConflict && targetName.isNotBlank()) {
                    resolver.reserve(folder, targetName)
                }
                hasConflict
            } else {
                false
            }
            previewRows += mapOf(
                "index" to index,
                "action" to plan.action,
                "image_id" to (plan.imageId ?: 0),
                "source_uri" to plan.sourceUri,
                "target_folder_uri" to plan.targetFolderUri,
                "target_name" to plan.targetName,
                "conflict" to conflict,
                "conflict_mode" to plan.conflictMode,
                "can_undo" to plan.canUndo,
            )
        }

        return mapOf(
            "ok" to true,
            "operations" to previewRows,
            "total" to previewRows.size,
            "_plans" to plans,
        )
    }

    private fun executePlan(
        plan: FileOperationPlan,
        recordsById: Map<Int, LocalRepository.ImageRecord>,
    ): Map<String, Any> {
        return when (plan.action) {
            "rename_image", "batch_rename_images" -> executeRenameImage(plan, recordsById)
            "rename_folder" -> executeRenameFolder(plan)
            "create_folder" -> executeCreateFolder(plan)
            "delete_folder" -> executeDeleteFolder(plan)
            "delete_images" -> executeDeleteImage(plan, recordsById)
            "move_images" -> executeMoveImage(plan, recordsById)
            "copy_images" -> executeCopyImage(plan, recordsById)
            else -> mapOf("ok" to false, "action" to plan.action, "message" to "unsupported action")
        }
    }

    private fun executeRenameImage(plan: FileOperationPlan, recordsById: Map<Int, LocalRepository.ImageRecord>): Map<String, Any> {
        val imageId = plan.imageId ?: return mapOf("ok" to false, "action" to plan.action, "message" to "image id missing")
        val record = recordsById[imageId] ?: repository.getImageRecordsByIds(listOf(imageId)).firstOrNull()
            ?: return mapOf("ok" to false, "action" to plan.action, "message" to "image not found")
        val requestedName = plan.targetName.trim().ifBlank { return mapOf("ok" to false, "action" to plan.action, "image_id" to imageId, "message" to "name is required") }
        val renameOutcome = renameImageWithConflictHandling(record.uri, record.folderUri, requestedName, plan.conflictMode)
        val finalName = renameOutcome.finalName
        val renamed = renameOutcome.result
        if (!renamed.ok || renamed.uri.isNullOrBlank()) {
            return mapOf("ok" to false, "action" to plan.action, "image_id" to imageId, "message" to renamed.message)
        }
        val dbOk = repository.updateImagePathAndClearThumbnails(
            imageId = imageId,
            newUri = renamed.uri,
            newFilename = finalName,
            newFolderUri = record.folderUri,
            newParentUri = record.parentUri,
            newFolderName = FolderUriUtils.displayName(record.folderUri),
            newRelativePath = "$record.parentUri/$finalName",
            newModifiedAtMs = System.currentTimeMillis(),
            oldUri = record.uri,
        )
        if (!dbOk) {
            return mapOf("ok" to false, "action" to plan.action, "image_id" to imageId, "message" to "database update failed")
        }
        return mapOf("ok" to true, "action" to plan.action, "image_id" to imageId, "new_uri" to renamed.uri, "new_name" to finalName)
    }

    private data class RenameAttemptOutcome(
        val result: StorageWriteResult,
        val finalName: String,
    )

    private fun renameImageWithConflictHandling(sourceUri: String, sourceFolderUri: String, requestedName: String, mode: String): RenameAttemptOutcome {
        val normalizedMode = mode.trim().lowercase().ifBlank { "rename" }
        val firstAttempt = storageProvider.rename(sourceUri, requestedName)
        if (normalizedMode != "rename") {
            return RenameAttemptOutcome(firstAttempt, requestedName)
        }
        if (firstAttempt.ok) {
            return RenameAttemptOutcome(firstAttempt, requestedName)
        }

        val firstMessage = firstAttempt.message.lowercase()
        if (!firstMessage.contains("conflict") || sourceFolderUri.isBlank()) {
            return RenameAttemptOutcome(firstAttempt, requestedName)
        }

        // Build one in-memory name set to avoid repeated expensive SAF rename retries.
        val existingNames = storageProvider.listChildren(sourceFolderUri)
            .map { it.name.lowercase() }
            .toMutableSet()
        var suffix = 1
        var candidate = withNumericSuffix(requestedName, suffix)
        while (existingNames.contains(candidate.lowercase())) {
            suffix += 1
            if (suffix > 1024) {
                return RenameAttemptOutcome(firstAttempt, requestedName)
            }
            candidate = withNumericSuffix(requestedName, suffix)
        }

        val secondAttempt = storageProvider.rename(sourceUri, candidate)
        return RenameAttemptOutcome(secondAttempt, candidate)
    }

    private fun withNumericSuffix(name: String, index: Int): String {
        val ext = name.substringAfterLast('.', "")
        val base = if (ext.isBlank()) name else name.removeSuffix(".$ext")
        return if (ext.isBlank()) "$base ($index)" else "$base ($index).$ext"
    }

    private fun executeRenameFolder(plan: FileOperationPlan): Map<String, Any> {
        val renamed = storageProvider.rename(plan.sourceUri, plan.targetName)
        if (!renamed.ok || renamed.uri.isNullOrBlank()) {
            return mapOf("ok" to false, "action" to plan.action, "message" to renamed.message)
        }
        val dbOk = repository.renameFolderAndLibraryUri(plan.sourceFolderUri, renamed.uri)
        if (!dbOk) {
            return mapOf("ok" to false, "action" to plan.action, "message" to "database update failed")
        }
        return mapOf("ok" to true, "action" to plan.action, "old_uri" to plan.sourceFolderUri, "new_uri" to renamed.uri)
    }

    private fun executeCreateFolder(plan: FileOperationPlan): Map<String, Any> {
        val created = storageProvider.createFolder(plan.targetFolderUri, plan.targetName)
        if (!created.ok || created.uri.isNullOrBlank()) {
            return mapOf("ok" to false, "action" to plan.action, "message" to created.message)
        }
        repository.registerFolder(created.uri, enabled = true)
        return mapOf("ok" to true, "action" to plan.action, "folder_uri" to created.uri, "changed" to created.changed)
    }

    private fun executeDeleteFolder(plan: FileOperationPlan): Map<String, Any> {
        val deleted = storageProvider.delete(plan.sourceUri)
        if (!deleted.ok) {
            return mapOf("ok" to false, "action" to plan.action, "message" to deleted.message)
        }
        repository.removeFolder(plan.sourceFolderUri)
        return mapOf("ok" to true, "action" to plan.action, "folder_uri" to plan.sourceFolderUri)
    }

    private fun executeDeleteImage(plan: FileOperationPlan, recordsById: Map<Int, LocalRepository.ImageRecord>): Map<String, Any> {
        val imageId = plan.imageId ?: return mapOf("ok" to false, "action" to plan.action, "message" to "image id missing")
        val record = recordsById[imageId] ?: repository.getImageRecordsByIds(listOf(imageId)).firstOrNull()
            ?: return mapOf("ok" to false, "action" to plan.action, "message" to "image not found")
        val deleted = storageProvider.delete(record.uri)
        if (!deleted.ok) {
            return mapOf("ok" to false, "action" to plan.action, "image_id" to imageId, "message" to deleted.message)
        }
        val dbOk = repository.deleteImageAndThumbnail(imageId, record.uri)
        if (!dbOk) {
            return mapOf("ok" to false, "action" to plan.action, "image_id" to imageId, "message" to "database update failed")
        }
        return mapOf("ok" to true, "action" to plan.action, "image_id" to imageId)
    }

    private fun executeMoveImage(
        plan: FileOperationPlan,
        recordsById: Map<Int, LocalRepository.ImageRecord>,
    ): Map<String, Any> {
        val imageId = plan.imageId ?: return mapOf("ok" to false, "action" to plan.action, "message" to "image id missing")
        val record = recordsById[imageId] ?: repository.getImageRecordsByIds(listOf(imageId)).firstOrNull()
            ?: return mapOf("ok" to false, "action" to plan.action, "message" to "image not found")
        val finalName = plan.targetName
        val moved = storageProvider.move(record.uri, plan.targetFolderUri, finalName)
        if (!moved.ok || moved.uri.isNullOrBlank()) {
            return mapOf("ok" to false, "action" to plan.action, "image_id" to imageId, "message" to moved.message)
        }
        val dbOk = repository.updateImagePathAndClearThumbnails(
            imageId = imageId,
            newUri = moved.uri,
            newFilename = finalName,
            newFolderUri = plan.targetFolderUri,
            newParentUri = plan.targetFolderUri,
            newFolderName = FolderUriUtils.displayName(plan.targetFolderUri),
            newRelativePath = "$plan.targetFolderUri/$finalName",
            newModifiedAtMs = System.currentTimeMillis(),
            oldUri = record.uri,
        )
        if (!dbOk) {
            return mapOf("ok" to false, "action" to plan.action, "image_id" to imageId, "message" to "database update failed")
        }
        return mapOf("ok" to true, "action" to plan.action, "image_id" to imageId, "new_uri" to moved.uri)
    }

    private fun executeCopyImage(
        plan: FileOperationPlan,
        recordsById: Map<Int, LocalRepository.ImageRecord>,
    ): Map<String, Any> {
        val imageId = plan.imageId ?: return mapOf("ok" to false, "action" to plan.action, "message" to "image id missing")
        val record = recordsById[imageId] ?: repository.getImageRecordsByIds(listOf(imageId)).firstOrNull()
            ?: return mapOf("ok" to false, "action" to plan.action, "message" to "image not found")
        val finalName = plan.targetName
        val copied = storageProvider.copy(record.uri, plan.targetFolderUri, finalName)
        if (!copied.ok || copied.uri.isNullOrBlank()) {
            return mapOf("ok" to false, "action" to plan.action, "image_id" to imageId, "message" to copied.message)
        }
        val scannedAt = System.currentTimeMillis()
        val importOrder = scannedAt * 1_000_000L + imageId
        val newId = repository.insertCopiedImageRecord(
            source = record,
            newUri = copied.uri,
            newFilename = finalName,
            newFolderUri = plan.targetFolderUri,
            newParentUri = plan.targetFolderUri,
            newFolderName = FolderUriUtils.displayName(plan.targetFolderUri),
            newRelativePath = "$plan.targetFolderUri/$finalName",
            scannedAtMs = scannedAt,
            importOrder = importOrder,
        )
        return mapOf("ok" to (newId != null), "action" to plan.action, "image_id" to imageId, "copied_image_id" to (newId ?: 0), "new_uri" to copied.uri)
    }

    private fun inversePlan(plan: FileOperationPlan, result: Map<String, Any>): FileOperationPlan? {
        if (!plan.canUndo) {
            return null
        }
        return when (plan.action) {
            "rename_image", "batch_rename_images" -> FileOperationPlan(
                action = "rename_image",
                imageId = plan.imageId,
                sourceUri = result["new_uri"]?.toString().orEmpty(),
                sourceName = plan.targetName,
                sourceFolderUri = plan.sourceFolderUri,
                targetFolderUri = plan.sourceFolderUri,
                targetName = plan.sourceName,
                conflictMode = "rename",
            )
            "move_images" -> FileOperationPlan(
                action = "move_images",
                imageId = plan.imageId,
                sourceUri = result["new_uri"]?.toString().orEmpty(),
                sourceName = plan.sourceName,
                sourceFolderUri = plan.targetFolderUri,
                targetFolderUri = plan.sourceFolderUri,
                targetName = plan.sourceName,
                conflictMode = "rename",
            )
            "copy_images" -> {
                val copiedId = (result["copied_image_id"] as? Number)?.toInt()
                if (copiedId == null || copiedId <= 0) {
                    null
                } else {
                    FileOperationPlan(
                        action = "delete_images",
                        imageId = copiedId,
                        sourceUri = result["new_uri"]?.toString().orEmpty(),
                        sourceFolderUri = plan.targetFolderUri,
                        canUndo = false,
                    )
                }
            }
            "create_folder" -> FileOperationPlan(
                action = "delete_folder",
                sourceUri = result["folder_uri"]?.toString().orEmpty(),
                sourceFolderUri = result["folder_uri"]?.toString().orEmpty(),
                canUndo = false,
            )
            "rename_folder" -> FileOperationPlan(
                action = "rename_folder",
                sourceUri = result["new_uri"]?.toString().orEmpty(),
                sourceFolderUri = result["new_uri"]?.toString().orEmpty(),
                targetName = FolderUriUtils.displayName(plan.sourceFolderUri),
            )
            else -> null
        }
    }

    private fun parseImageIds(raw: Any?): List<Int> {
        return when (raw) {
            is List<*> -> raw.mapNotNull {
                when (it) {
                    is Number -> it.toInt()
                    else -> it?.toString()?.trim()?.toIntOrNull()
                }
            }
            else -> raw?.toString()
                ?.split(',', '|', ' ')
                ?.mapNotNull { it.trim().toIntOrNull() }
                ?: emptyList()
        }.distinct()
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
            "skipped_entries" to scanSkipped,
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

    private fun extractMetadata(node: StorageNode): ScanMetadata {
        val size = node.sizeBytes
        val modified = node.lastModifiedMs
        val created = modified
        val extension = node.name.substringAfterLast('.', "").lowercase()
        val mimeType = mimeTypeFromExtension(extension)
        val bounds = BitmapFactory.Options().apply {
            inJustDecodeBounds = true
        }
        storageProvider.openInputStream(node.uri)?.use { input ->
            BitmapFactory.decodeStream(input, null, bounds)
        }
        val width = bounds.outWidth.takeIf { it > 0 }
        val height = bounds.outHeight.takeIf { it > 0 }
        val resolution = if (width != null && height != null) "${width}x${height}" else null
        val aspectRatio = if (width != null && height != null && height != 0) width.toDouble() / height.toDouble() else null
        val orientation = if (width != null && height != null) {
            when {
                width > height -> "landscape"
                width < height -> "portrait"
                else -> "square"
            }
        } else {
            null
        }
        val folderName = FolderUriUtils.displayName(node.parentUri.orEmpty())
        val relativePath = node.parentUri?.let { parent ->
            val parentName = parent.substringAfterLast('/', "")
            if (parentName.isBlank()) {
                node.name
            } else {
                "$parentName/${node.name}"
            }
        } ?: node.name
        return ScanMetadata(
            width = width,
            height = height,
            createdAtMs = created,
            modifiedAtMs = modified,
            sizeBytes = size,
            extension = extension,
            mimeType = mimeType,
            resolution = resolution,
            aspectRatio = aspectRatio,
            orientation = orientation,
            folderName = folderName,
            relativePath = relativePath,
            indexedAtMs = System.currentTimeMillis(),
        )
    }

    private fun buildMetadataText(node: StorageNode, metadata: ScanMetadata): String {
        val segments = mutableListOf<String>()
        segments += node.name
        segments += node.uri
        node.parentUri?.let { segments += it }
        metadata.width?.let { segments += "width:$it" }
        metadata.height?.let { segments += "height:$it" }
        metadata.resolution?.let { segments += "resolution:$it" }
        metadata.orientation?.let { segments += "orientation:$it" }
        if (metadata.extension.isNotBlank()) {
            segments += "extension:${metadata.extension}"
        }
        if (metadata.mimeType.isNotBlank()) {
            segments += "mime:${metadata.mimeType}"
        }
        metadata.sizeBytes?.let { segments += "size:$it" }
        metadata.modifiedAtMs?.let { segments += "modified:$it" }
        if (metadata.folderName.isNotBlank()) {
            segments += "folder:${metadata.folderName}"
        }
        if (metadata.relativePath.isNotBlank()) {
            segments += "relative:${metadata.relativePath}"
        }
        return segments.joinToString(" ")
    }

    private fun Map<String, Any>.toQueryOptions(): LibraryQueryOptions {
        val tags = (this["tags"] as? List<*>)
            ?.mapNotNull { it?.toString() }
            ?.filter { it.isNotBlank() }
            ?: emptyList()

        val taxonomy = (this["taxonomy_filters"] as? Map<*, *>)
            ?.entries
            ?.mapNotNull { (k, v) ->
                val key = k?.toString()?.trim().orEmpty()
                val value = v?.toString()?.trim().orEmpty()
                if (key.isBlank() || value.isBlank()) null else key to value
            }
            ?.toMap()
            ?: emptyMap()

        return LibraryQueryOptions(
            query = this["query"]?.toString(),
            imageId = (this["image_id"] as? Number)?.toInt() ?: this["image_id"]?.toString()?.toIntOrNull(),
            fullText = this["full_text"]?.toString(),
            sortBy = this["sort_by"]?.toString()?.ifBlank { "import_order" } ?: "import_order",
            sortDirection = this["sort_direction"]?.toString()?.ifBlank { "desc" } ?: "desc",
            page = (this["page"] as? Number)?.toInt() ?: this["page"]?.toString()?.toIntOrNull() ?: 1,
            pageSize = (this["page_size"] as? Number)?.toInt() ?: this["page_size"]?.toString()?.toIntOrNull() ?: 0,
            collection = this["collection"]?.toString(),
            favoritesOnly = when (val raw = this["favorites_only"]) {
                is Boolean -> raw
                is Number -> raw.toInt() != 0
                else -> raw?.toString()?.equals("true", ignoreCase = true) == true
            },
            minRating = (this["min_rating"] as? Number)?.toInt() ?: this["min_rating"]?.toString()?.toIntOrNull(),
            maxRating = (this["max_rating"] as? Number)?.toInt() ?: this["max_rating"]?.toString()?.toIntOrNull(),
            tags = tags,
            minWidth = (this["min_width"] as? Number)?.toInt() ?: this["min_width"]?.toString()?.toIntOrNull(),
            minHeight = (this["min_height"] as? Number)?.toInt() ?: this["min_height"]?.toString()?.toIntOrNull(),
            fileFormat = this["file_format"]?.toString(),
            orientation = this["orientation"]?.toString(),
            folderQuery = this["folder_query"]?.toString(),
            includeHidden = when (val raw = this["include_hidden"]) {
                is Boolean -> raw
                is Number -> raw.toInt() != 0
                else -> raw?.toString()?.equals("true", ignoreCase = true) == true
            },
            missingOnly = when (val raw = this["missing_only"]) {
                is Boolean -> raw
                is Number -> raw.toInt() != 0
                else -> raw?.toString()?.equals("true", ignoreCase = true) == true
            },
            taxonomyFilters = taxonomy,
            includeInactive = when (val raw = this["include_inactive"]) {
                is Boolean -> raw
                is Number -> raw.toInt() != 0
                else -> raw?.toString()?.equals("true", ignoreCase = true) == true
            },
        )
    }

    private fun parseFusionImportFormat(raw: String): FusionImportFormat {
        val normalized = raw.trim().lowercase()
        return when (normalized) {
            "json" -> FusionImportFormat.JSON
            "workbook", "workbook_compat", "workbook-compatible", "workbook_compatible" -> FusionImportFormat.WORKBOOK_COMPAT
            else -> FusionImportFormat.JSON
        }
    }

    private fun parseExternalImportSourceType(raw: String): ExternalImportSourceType {
        val normalized = raw.trim().lowercase()
        return when (normalized) {
            "json", "fusion_json" -> ExternalImportSourceType.JSON
            "workbook", "workbook_compat", "workbook-compatible", "workbook_compatible", "workbook_compat_json" -> {
                ExternalImportSourceType.WORKBOOK_COMPAT_JSON
            }
            "csv" -> ExternalImportSourceType.CSV
            "sqlite", "sqlite3", "db" -> ExternalImportSourceType.SQLITE
            else -> ExternalImportSourceType.JSON
        }
    }

    private fun parseExternalConflictStrategy(raw: String): ExternalImportConflictStrategy {
        val normalized = raw.trim().lowercase()
        return when (normalized) {
            "skip" -> ExternalImportConflictStrategy.SKIP
            "overwrite" -> ExternalImportConflictStrategy.OVERWRITE
            "keep_both", "keep-both", "keepboth" -> ExternalImportConflictStrategy.KEEP_BOTH
            "rename_imported", "rename-imported", "renameimported" -> ExternalImportConflictStrategy.RENAME_IMPORTED
            "merge_metadata", "merge-metadata", "mergemetadata" -> ExternalImportConflictStrategy.MERGE_METADATA
            else -> ExternalImportConflictStrategy.MERGE_METADATA
        }
    }

    private fun parseAliasHints(raw: Any?): Map<String, Map<String, String>> {
        val source = raw as? Map<*, *> ?: return emptyMap()
        val result = mutableMapOf<String, Map<String, String>>()
        source.forEach { (categoryRaw, mappingRaw) ->
            val category = categoryRaw?.toString()?.trim().orEmpty()
            if (category.isBlank()) {
                return@forEach
            }
            val mapping = mappingRaw as? Map<*, *> ?: return@forEach
            val normalizedMapping = mutableMapOf<String, String>()
            mapping.forEach { (aliasRaw, idRaw) ->
                val alias = aliasRaw?.toString()?.trim().orEmpty()
                val id = idRaw?.toString()?.trim().orEmpty()
                if (alias.isNotBlank() && id.isNotBlank()) {
                    normalizedMapping[alias] = id
                }
            }
            result[category] = normalizedMapping
        }
        return result
    }

    private fun parseBooleanFlag(raw: Any?, defaultValue: Boolean): Boolean {
        return when (raw) {
            null -> defaultValue
            is Boolean -> raw
            is Number -> raw.toInt() != 0
            else -> raw.toString().trim().equals("true", ignoreCase = true)
        }
    }

    private fun Map<String, Any>.toExternalImportRequest(): ExternalImportRequest {
        val importId = this["import_id"]?.toString()?.trim()?.ifBlank { UUID.randomUUID().toString() }
            ?: UUID.randomUUID().toString()
        val rawSourceType = this["source_type"]?.toString()
            ?: this["sourceType"]?.toString()
            ?: this["format"]?.toString()
            ?: "json"
        val source = this["source"]?.toString()
            ?: this["payload"]?.toString()
            ?: ""
        require(source.isNotBlank()) { "Import source is required." }

        val conflictRaw = this["conflict_strategy"]?.toString()
            ?: this["conflictStrategy"]?.toString()
            ?: "merge_metadata"

        val replaceExisting = parseBooleanFlag(
            this["replace_existing"] ?: this["replaceExisting"],
            defaultValue = false,
        )
        val csvTableName = this["csv_table_name"]?.toString() ?: this["csvTableName"]?.toString()
        val aliasHints = parseAliasHints(this["alias_hints"] ?: this["aliasHints"])

        return ExternalImportRequest(
            importId = importId,
            sourceType = parseExternalImportSourceType(rawSourceType),
            source = source,
            conflictStrategy = parseExternalConflictStrategy(conflictRaw),
            replaceExisting = replaceExisting,
            csvTableName = csvTableName,
            aliasHints = aliasHints,
        )
    }

    private fun imageSummary(image: Map<String, Any>?): String {
        if (image == null) {
            return "null"
        }
        val metadata = image["metadata"] as? Map<*, *>
        val tags = when (val nested = metadata?.get("tags")) {
            is List<*> -> nested.mapNotNull { it?.toString() }.joinToString("|")
            is String -> nested
            else -> ""
        }
        return "id=${image["image_id"]} favorite=${image["favorite"]} rating=${image["rating"]} tags=$tags"
    }

    private fun Map<String, Any>.toSemanticCandidatePayloadOrNull(): Map<String, Any>? {
        val imageId = this["image_id"].toIntOrNullValue() ?: return null
        val metadata = this["metadata"] as? Map<*, *>
        val tags = when (val nested = metadata?.get("tags")) {
            is List<*> -> nested.mapNotNull { it?.toString()?.trim() }.filter { it.isNotBlank() }
            is String -> nested.split(',', '|', ';').map { it.trim() }.filter { it.isNotBlank() }
            else -> ""
        }
        val tagsText = when (tags) {
            is List<*> -> tags.joinToString(" ")
            is String -> tags
            else -> ""
        }
        val taxonomyText = metadata?.get("taxonomy_text")?.toString().orEmpty()
        val metadataText = metadata?.get("metadata_text")?.toString().orEmpty()
        val folderName = metadata?.get("folder_name")?.toString().orEmpty()
        val relativePath = metadata?.get("relative_path")?.toString().orEmpty()

        val text = listOf(
            this["filename"]?.toString().orEmpty(),
            this["path"]?.toString().orEmpty(),
            folderName,
            relativePath,
            tagsText,
            taxonomyText,
            metadataText,
        ).filter { it.isNotBlank() }.joinToString(" ")

        return mapOf(
            "image_id" to imageId,
            "text" to text,
            "filename" to this["filename"]?.toString().orEmpty(),
            "path" to this["path"]?.toString().orEmpty(),
            "metadata" to (metadata?.toStringAnyMap() ?: emptyMap<String, Any>()),
            "tags" to (if (tags is List<*>) tags else emptyList<String>()),
            "favorite" to parseBooleanFlag(this["favorite"], defaultValue = false),
            "rating" to (this["rating"].toIntOrNullValue() ?: 0),
        )
    }

    private fun prepareAiPipelinePayload(payload: Map<String, Any>): Map<String, Any> {
        val prepared = linkedMapOf<String, Any>()
        prepared.putAll(payload)

        val imageId = prepared["image_id"].toIntOrNullValue()
        if (imageId != null) {
            val image = repository.searchByImageId(imageId)
            if (image != null) {
                prepared.putIfAbsent("image_id", imageId)
                prepared.putIfAbsent("filename", image["filename"]?.toString().orEmpty())
                prepared.putIfAbsent("path", image["path"]?.toString().orEmpty())
                prepared.putIfAbsent("uri", image["uri"]?.toString().orEmpty())
                prepared.putIfAbsent("favorite", parseBooleanFlag(image["favorite"], defaultValue = false))
                prepared.putIfAbsent("rating", image["rating"]?.toString()?.toIntOrNull() ?: 0)

                val metadata = (image["metadata"] as? Map<*, *>)?.toStringAnyMap() ?: emptyMap()
                if (metadata.isNotEmpty() && (prepared["metadata"] as? Map<*, *>) == null) {
                    prepared["metadata"] = metadata
                }
                if (prepared["tags"] !is List<*> && metadata["tags"] != null) {
                    prepared["tags"] = metadata["tags"].toStringList()
                }
            }
        }

        val normalizedTaskType = extractPipelineTaskType(prepared)
        if (normalizedTaskType in setOf("similarity_search", "duplicate_detection")) {
            val existingCandidates = (prepared["candidates"] as? List<*>)
                ?.mapNotNull { (it as? Map<*, *>)?.toStringAnyMap() }
                ?: emptyList()
            if (existingCandidates.isEmpty()) {
                val candidateLimit = prepared["candidate_limit"].toIntOrNullValue()?.coerceIn(1, 2_000)
                    ?: if (normalizedTaskType == "duplicate_detection") 800 else 600
                val candidateImageIds = (prepared["image_ids"] as? List<*>)
                    ?.mapNotNull { it.toIntOrNullValue() }
                    ?.distinct()
                    ?: emptyList()

                val candidateRows = if (candidateImageIds.isNotEmpty()) {
                    candidateImageIds.mapNotNull { id -> repository.searchByImageId(id) }
                } else {
                    val options = prepared.toQueryOptions().copy(
                        query = null,
                        fullText = null,
                        sortBy = "import_order",
                        sortDirection = "desc",
                        page = 1,
                        pageSize = 0,
                    )
                    repository.searchImages(options)
                }
                prepared["candidates"] = candidateRows.take(candidateLimit).mapNotNull { row -> row.toSemanticCandidatePayloadOrNull() }
            }
        }

        return prepared
    }

    private fun applyPipelineSideEffects(requestPayload: Map<String, Any>, response: Map<String, Any>) {
        val ok = parseBooleanFlag(response["ok"], defaultValue = false)
        if (!ok) {
            return
        }

        val taskType = extractPipelineTaskType(requestPayload)
        if (taskType != "tag_prediction") {
            return
        }

        val imageId = requestPayload["image_id"].toIntOrNullValue() ?: return
        val tags = extractPredictedTags(response)
        if (tags.isEmpty()) {
            return
        }
        repository.setTags(imageId, tags)
    }

    private fun extractPredictedTags(response: Map<String, Any>): List<String> {
        val result = (response["result"] as? Map<*, *>)?.toStringAnyMap() ?: emptyMap()
        val direct = result["tags"].toStringList()
        if (direct.isNotEmpty()) {
            return direct
        }

        val rawResult = (response["raw_result"] as? Map<*, *>)?.toStringAnyMap() ?: emptyMap()
        val nested = (rawResult["result"] as? Map<*, *>)?.toStringAnyMap() ?: emptyMap()
        return nested["tags"].toStringList()
    }

    private fun extractPipelineTaskType(payload: Map<String, Any>): String {
        val raw = payload["task_type"]?.toString()?.trim().orEmpty()
            .ifBlank { payload["pipeline_type"]?.toString()?.trim().orEmpty() }
        return raw
            .lowercase()
            .replace('-', '_')
            .replace(' ', '_')
            .replace(Regex("_+"), "_")
    }

    private fun extractSemanticMatches(result: Map<String, Any>): List<Map<String, Any>> {
        val direct = (result["matches"] as? List<*>)
            ?.mapNotNull { item ->
                val map = item as? Map<*, *> ?: return@mapNotNull null
                map.toStringAnyMap()
            }
            ?: emptyList()
        if (direct.isNotEmpty()) {
            return direct
        }

        val nested = (result["result"] as? Map<*, *>)?.toStringAnyMap() ?: return emptyList()
        return (nested["matches"] as? List<*>)
            ?.mapNotNull { item ->
                val map = item as? Map<*, *> ?: return@mapNotNull null
                map.toStringAnyMap()
            }
            ?: emptyList()
    }

    private fun Map<*, *>.toStringAnyMap(): Map<String, Any> {
        val result = linkedMapOf<String, Any>()
        this.forEach { (keyRaw, value) ->
            val key = keyRaw?.toString()?.trim().orEmpty()
            if (key.isBlank() || value == null) {
                return@forEach
            }
            result[key] = value
        }
        return result
    }

    private fun Any?.toIntOrNullValue(): Int? {
        return when (this) {
            is Number -> this.toInt()
            else -> this?.toString()?.toIntOrNull()
        }
    }

    private fun Any?.toDoubleOrNullValue(): Double? {
        return when (this) {
            is Number -> this.toDouble()
            else -> this?.toString()?.toDoubleOrNull()
        }
    }

    private fun Any?.toStringList(): List<String> {
        return when (this) {
            is List<*> -> this.mapNotNull { it?.toString()?.trim() }.filter { it.isNotBlank() }
            is String -> this.split(',', '|', ';').map { it.trim() }.filter { it.isNotBlank() }
            else -> emptyList()
        }
    }

    private fun mimeTypeFromExtension(extension: String): String {
        return when (extension.lowercase()) {
            "jpg", "jpeg" -> "image/jpeg"
            "png" -> "image/png"
            "gif" -> "image/gif"
            "webp" -> "image/webp"
            "bmp" -> "image/bmp"
            "avif" -> "image/avif"
            "heif", "heic" -> "image/heic"
            "tif", "tiff" -> "image/tiff"
            else -> "application/octet-stream"
        }
    }

    private fun cleanupLegacySettings() {
        val prefs = appContext.getSharedPreferences("ailm_android", Context.MODE_PRIVATE)
        if (prefs.contains("backend_url")) {
            prefs.edit().remove("backend_url").apply()
        }
    }
}
