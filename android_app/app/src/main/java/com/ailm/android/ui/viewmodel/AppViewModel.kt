package com.ailm.android.ui.viewmodel

import android.os.SystemClock
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ailm.android.runtime.StandaloneRuntime
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class AppUiState(
    val loading: Boolean = false,
    val health: Map<String, Any> = emptyMap(),
    val stats: Map<String, Any> = emptyMap(),
    val images: List<Map<String, Any>> = emptyList(),
    val searchResults: List<Map<String, Any>> = emptyList(),
    val totalResults: Int = 0,
    val collections: List<Map<String, Any>> = emptyList(),
    val libraryFolders: List<Map<String, Any>> = emptyList(),
    val scanRuns: List<Map<String, Any>> = emptyList(),
    val downloads: List<Map<String, Any>> = emptyList(),
    val knowledgePacks: List<Map<String, Any>> = emptyList(),
    val reviewQueue: List<Map<String, Any>> = emptyList(),
    val tags: List<String> = emptyList(),
    val settingsValues: Map<String, String> = emptyMap(),
    val lastMaintenanceResult: Map<String, Any> = emptyMap(),
    val lastActionMessage: String? = null,
    val selectedLibraryUri: String = "",
    val scanStatus: String = "idle",
    val scanProgress: Double = 0.0,
    val scanDiscoveredImages: Int = 0,
    val selectedImage: Map<String, Any>? = null,
    val fileOperationPreview: List<Map<String, Any>> = emptyList(),
    val fileOperationResults: List<Map<String, Any>> = emptyList(),
    val fileOperationProgress: Double = 0.0,
    val fileOperationRunning: Boolean = false,
    val fileOperationUndoAvailable: Boolean = false,
    val firstLaunchCompleted: Boolean = false,
    val errorMessage: String? = null,
)

private const val VM_TRACE_TAG = "AilmTraceVM"
private const val FILE_OP_TIMING_TAG = "AilmFileOpTiming"

class AppViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(AppUiState())
    val uiState: StateFlow<AppUiState> = _uiState.asStateFlow()
    private var scanPollingJob: Job? = null

    fun initializeConfiguration(libraryUri: String) {
        _uiState.value = _uiState.value.copy(
            selectedLibraryUri = libraryUri,
            firstLaunchCompleted = libraryUri.isNotBlank(),
        )
    }

    fun setLibraryUri(uri: String) {
        val normalized = uri.trim()
        _uiState.value = _uiState.value.copy(
            selectedLibraryUri = normalized,
            firstLaunchCompleted = normalized.isNotBlank(),
        )
    }

    fun refreshDashboard() {
        viewModelScope.launch(Dispatchers.IO) {
            val previous = _uiState.value

            withContext(Dispatchers.Main) {
                _uiState.value = previous.copy(
                    loading = true,
                    errorMessage = null,
                )
            }

            try {
                val health = StandaloneRuntime.healthStatus()
                val stats = StandaloneRuntime.libraryStatistics()
                val images = StandaloneRuntime.getLibraryImages(pageSize = 0)
                val folders = StandaloneRuntime.listLibraryFolders(includeDisabled = true)
                val scanRuns = StandaloneRuntime.scanStatistics(limit = 100)
                val collections = StandaloneRuntime.getCollections()
                val downloads = StandaloneRuntime.listDownloads()
                val knowledgePacks = StandaloneRuntime.listKnowledgePacks()
                val reviewQueue = StandaloneRuntime.getReviewQueue()
                val tags = StandaloneRuntime.getTags()

                withContext(Dispatchers.Main) {
                    val current = _uiState.value
                    _uiState.value = AppUiState(
                        loading = false,
                        health = health,
                        stats = stats,
                        images = images,
                        searchResults = if (current.searchResults.isEmpty()) images else current.searchResults,
                        totalResults = if (current.searchResults.isEmpty()) images.size else current.totalResults,
                        collections = collections,
                        libraryFolders = folders,
                        scanRuns = scanRuns,
                        downloads = downloads,
                        knowledgePacks = knowledgePacks,
                        reviewQueue = reviewQueue,
                        tags = tags,
                        settingsValues = current.settingsValues,
                        lastMaintenanceResult = current.lastMaintenanceResult,
                        lastActionMessage = current.lastActionMessage,
                        selectedLibraryUri = current.selectedLibraryUri,
                        scanStatus = current.scanStatus,
                        scanProgress = current.scanProgress,
                        scanDiscoveredImages = current.scanDiscoveredImages,
                        selectedImage = current.selectedImage,
                        fileOperationPreview = current.fileOperationPreview,
                        fileOperationResults = current.fileOperationResults,
                        fileOperationProgress = current.fileOperationProgress,
                        fileOperationRunning = current.fileOperationRunning,
                        fileOperationUndoAvailable = current.fileOperationUndoAvailable,
                        firstLaunchCompleted = current.firstLaunchCompleted,
                        errorMessage = null,
                    )
                }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    _uiState.value = previous.copy(
                        loading = false,
                        errorMessage = t.message ?: t.javaClass.simpleName,
                    )
                }
            }
        }
    }

    fun startScan() {
        val root = _uiState.value.selectedLibraryUri.trim()
        if (root.isBlank()) {
            _uiState.value = _uiState.value.copy(errorMessage = "Choose a library folder first.")
            return
        }

        viewModelScope.launch(Dispatchers.IO) {
            try {
                StandaloneRuntime.startScan(root)
                withContext(Dispatchers.Main) {
                    _uiState.value = _uiState.value.copy(
                        scanStatus = "running",
                        errorMessage = null,
                        lastActionMessage = "Scan started.",
                    )
                }
                refreshScanStatus()
                ensureScanPolling()
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    _uiState.value = _uiState.value.copy(errorMessage = t.message ?: t.javaClass.simpleName)
                }
            }
        }
    }

    fun pauseScan() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { StandaloneRuntime.pauseScan() }
            refreshScanStatus()
            ensureScanPolling()
        }
    }

    fun resumeScan() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { StandaloneRuntime.resumeScan() }
            refreshScanStatus()
            ensureScanPolling()
        }
    }

    fun cancelScan() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { StandaloneRuntime.cancelScan() }
            refreshScanStatus()
        }
    }

    fun refreshScanStatus() {
        viewModelScope.launch(Dispatchers.IO) {
            updateScanState()
        }
    }

    fun searchByFilename(query: String) {
        runIoAction {
            val items = StandaloneRuntime.searchByFilename(query)
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    searchResults = items,
                    totalResults = items.size,
                    errorMessage = null,
                    lastActionMessage = "Filename search returned ${items.size} item(s).",
                )
            }
        }
    }

    fun searchByImageId(rawId: String) {
        val normalized = rawId.trim()
        if (normalized.isBlank()) {
            _uiState.value = _uiState.value.copy(
                searchResults = _uiState.value.images,
                totalResults = _uiState.value.images.size,
                errorMessage = null,
            )
            return
        }
        val imageId = normalized.toIntOrNull()
        if (imageId == null) {
            _uiState.value = _uiState.value.copy(
                searchResults = emptyList(),
                totalResults = 0,
                errorMessage = null,
            )
            return
        }
        runIoAction {
            val item = StandaloneRuntime.searchByImageId(imageId)
            val items = if (item == null) emptyList() else listOf(item)
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    searchResults = items,
                    totalResults = items.size,
                    errorMessage = null,
                    lastActionMessage = "Image ID search returned ${items.size} item(s).",
                )
            }
        }
    }

    fun runAdvancedSearch(payload: Map<String, Any>) {
        runIoAction {
            val response = StandaloneRuntime.advancedSearch(payload)
            val items = response["items"] as? List<Map<String, Any>> ?: emptyList()
            val count = response["count"].asIntOrZero()
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    searchResults = items,
                    totalResults = count,
                    errorMessage = null,
                    lastActionMessage = "Advanced search returned $count item(s).",
                )
            }
        }
    }

    fun runSemanticSearch(query: String) {
        val normalizedQuery = query.trim()
        runIoAction {
            val items = StandaloneRuntime.semanticSearch(
                queryVector = emptyList(),
                payload = mapOf(
                    "query" to normalizedQuery,
                    "top_k" to 200,
                    "candidate_limit" to 600,
                ),
            )
            withContext(Dispatchers.Main) {
                val message = if (normalizedQuery.isBlank()) {
                    "Semantic search returned ${items.size} item(s)."
                } else {
                    "Semantic search for '$normalizedQuery' returned ${items.size} item(s)."
                }
                _uiState.value = _uiState.value.copy(
                    searchResults = items,
                    totalResults = items.size,
                    errorMessage = null,
                    lastActionMessage = message,
                )
            }
        }
    }

    fun clearSearchResults() {
        _uiState.value = _uiState.value.copy(
            searchResults = _uiState.value.images,
            totalResults = _uiState.value.images.size,
        )
    }

    fun addLibraryFolder(folderUri: String) {
        val uri = folderUri.trim()
        if (uri.isBlank()) {
            _uiState.value = _uiState.value.copy(errorMessage = "Folder URI is required.")
            return
        }
        runIoAction {
            val ok = StandaloneRuntime.addLibraryFolder(uri)
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    lastActionMessage = if (ok) "Folder added." else "Folder was not added.",
                )
            }
            refreshDashboard()
        }
    }

    fun setLibraryFolderEnabled(folderUri: String, enabled: Boolean) {
        runIoAction {
            val ok = StandaloneRuntime.setLibraryFolderEnabled(folderUri, enabled)
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    lastActionMessage = if (ok) {
                        if (enabled) "Folder enabled." else "Folder disabled."
                    } else {
                        "Folder update failed."
                    },
                )
            }
            refreshDashboard()
        }
    }

    fun removeLibraryFolder(folderUri: String) {
        runIoAction {
            val ok = StandaloneRuntime.removeLibraryFolder(folderUri)
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    lastActionMessage = if (ok) "Folder removed." else "Folder remove failed.",
                )
            }
            refreshDashboard()
        }
    }

    fun rescanFolder(folderUri: String) {
        runIoAction {
            StandaloneRuntime.rescanFolder(folderUri)
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    scanStatus = "running",
                    lastActionMessage = "Folder rescan started.",
                )
            }
            refreshScanStatus()
            ensureScanPolling()
        }
    }

    fun rescanEnabledFolders() {
        runIoAction {
            val runs = StandaloneRuntime.rescanEnabledFolders()
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    scanStatus = if (runs.isNotEmpty()) "running" else _uiState.value.scanStatus,
                    lastActionMessage = "Requested rescan for ${runs.size} enabled folder(s).",
                )
            }
            refreshScanStatus()
            ensureScanPolling()
        }
    }

    fun setImageFavorite(imageId: Int, favorite: Boolean) {
        Log.d(VM_TRACE_TAG, "ViewModel receives favorite: imageId=$imageId nextFavorite=$favorite")
        runIoAction {
            val ok = StandaloneRuntime.setImageFavorite(imageId, favorite)
            Log.d(VM_TRACE_TAG, "ViewModel favorite runtime result: imageId=$imageId ok=$ok")
            var updatedImage: Map<String, Any>? = null
            withContext(Dispatchers.Main) {
                if (ok) {
                    updatedImage = updateImageState(imageId) { image ->
                        val metadata = (image["metadata"] as? Map<*, *>)
                            ?.mapNotNull { (key, value) -> (key as? String)?.let { it to value } }
                            ?.toMap()
                            ?.toMutableMap()
                            ?: mutableMapOf()
                        metadata["favorite"] = favorite
                        image.toMutableMap().apply {
                            this["favorite"] = favorite
                            this["metadata"] = metadata
                        }
                    }
                    Log.d(VM_TRACE_TAG, "ViewModel favorite state staged: imageId=$imageId updatedImage=${imageSummary(updatedImage)}")
                } else {
                    val currentSelectedId = _uiState.value.selectedImage?.get("image_id")
                    Log.d(
                        VM_TRACE_TAG,
                        "Favorite update failed: requestedImageId=$imageId currentUISelectedImageId=$currentSelectedId selectedImage=${imageSummary(_uiState.value.selectedImage)}",
                    )
                }
                _uiState.value = _uiState.value.copy(lastActionMessage = if (ok) {
                    if (favorite) "Marked favorite." else "Favorite removed."
                } else {
                    "Favorite update failed."
                })
            }
            if (ok) {
                refreshImageInState(imageId, updatedImage)
            }
        }
    }

    fun setImageRating(imageId: Int, rating: Int) {
        Log.d(VM_TRACE_TAG, "ViewModel receives rating: imageId=$imageId requestedRating=$rating")
        runIoAction {
            val bounded = rating.coerceIn(0, 5)
            val ok = StandaloneRuntime.setImageRating(imageId, bounded)
            Log.d(VM_TRACE_TAG, "ViewModel rating runtime result: imageId=$imageId boundedRating=$bounded ok=$ok")
            var updatedImage: Map<String, Any>? = null
            withContext(Dispatchers.Main) {
                if (ok) {
                    updatedImage = updateImageState(imageId) { image ->
                        val metadata = (image["metadata"] as? Map<*, *>)
                            ?.mapNotNull { (key, value) -> (key as? String)?.let { it to value } }
                            ?.toMap()
                            ?.toMutableMap()
                            ?: mutableMapOf()
                        metadata["rating"] = bounded
                        image.toMutableMap().apply {
                            this["rating"] = bounded
                            this["metadata"] = metadata
                        }
                    }
                    Log.d(VM_TRACE_TAG, "ViewModel rating state staged: imageId=$imageId updatedImage=${imageSummary(updatedImage)}")
                } else {
                    val currentSelectedId = _uiState.value.selectedImage?.get("image_id")
                    Log.d(
                        VM_TRACE_TAG,
                        "Rating update failed: requestedImageId=$imageId currentUISelectedImageId=$currentSelectedId selectedImage=${imageSummary(_uiState.value.selectedImage)}",
                    )
                }
                _uiState.value = _uiState.value.copy(lastActionMessage = if (ok) "Rating set to $bounded." else "Rating update failed.")
            }
            if (ok) {
                refreshImageInState(imageId, updatedImage)
            }
        }
    }

    fun setImageTags(imageId: Int, tagsCsv: String) {
        val tags = tagsCsv
            .split(',', '|')
            .map { it.trim().replace(Regex("\\s+"), " ") }
            .filter { it.isNotBlank() }
        Log.d(VM_TRACE_TAG, "ViewModel receives tags: imageId=$imageId input=$tagsCsv parsed=${tags.joinToString("|")}")
        runIoAction {
            val ok = StandaloneRuntime.setImageTags(imageId, tags)
            Log.d(VM_TRACE_TAG, "ViewModel tags runtime result: imageId=$imageId ok=$ok")
            var updatedImage: Map<String, Any>? = null
            withContext(Dispatchers.Main) {
                if (ok) {
                    updatedImage = updateImageState(imageId) { image ->
                        val metadata = (image["metadata"] as? Map<*, *>)
                            ?.mapNotNull { (key, value) -> (key as? String)?.let { it to value } }
                            ?.toMap()
                            ?.toMutableMap()
                            ?: mutableMapOf()
                        metadata["tags"] = tags
                        metadata["user_tags"] = tags.joinToString("|")
                        image.toMutableMap().apply {
                            this["metadata"] = metadata
                        }
                    }
                    Log.d(VM_TRACE_TAG, "ViewModel tags state staged: imageId=$imageId updatedImage=${imageSummary(updatedImage)}")
                } else {
                    val currentSelectedId = _uiState.value.selectedImage?.get("image_id")
                    Log.d(
                        VM_TRACE_TAG,
                        "Tags update failed: requestedImageId=$imageId currentUISelectedImageId=$currentSelectedId selectedImage=${imageSummary(_uiState.value.selectedImage)}",
                    )
                }
                _uiState.value = _uiState.value.copy(lastActionMessage = if (ok) "Tags updated." else "Tag update failed.")
            }
            if (ok) {
                refreshImageInState(imageId, updatedImage)
                val latestTags = StandaloneRuntime.getTags()
                withContext(Dispatchers.Main) {
                    _uiState.value = _uiState.value.copy(tags = latestTags)
                }
            }
        }
    }

    fun rebuildSearchIndex() {
        runIoAction {
            val ok = StandaloneRuntime.rebuildSearchIndex()
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    lastActionMessage = if (ok) "Search index rebuilt." else "Search index rebuild failed.",
                )
            }
            refreshDashboard()
        }
    }

    fun optimizeDatabase() {
        runIoAction {
            val ok = StandaloneRuntime.optimizeDatabase()
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    lastActionMessage = if (ok) "Database optimized." else "Database optimization failed.",
                )
            }
            refreshDashboard()
        }
    }

    fun maintainThumbnailCache(maxMb: Int) {
        val safeMb = maxMb.coerceAtLeast(1)
        runIoAction {
            val result = StandaloneRuntime.manageThumbnailCache(safeMb.toLong() * 1024L * 1024L)
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    lastMaintenanceResult = result,
                    lastActionMessage = "Thumbnail cache maintenance completed.",
                )
            }
        }
    }

    fun clearThumbnailCache() {
        runIoAction {
            val result = StandaloneRuntime.manageThumbnailCache(0)
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    lastMaintenanceResult = result,
                    lastActionMessage = "Thumbnail cache cleared.",
                )
            }
        }
    }

    fun refreshScanStatistics() {
        runIoAction {
            val runs = StandaloneRuntime.scanStatistics(limit = 100)
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(scanRuns = runs)
            }
        }
    }

    fun updateLibrarySetting(key: String, value: String) {
        val normalizedKey = key.trim()
        if (normalizedKey.isBlank()) {
            _uiState.value = _uiState.value.copy(errorMessage = "Setting key is required.")
            return
        }
        runIoAction {
            val ok = StandaloneRuntime.updateSetting(normalizedKey, value)
            withContext(Dispatchers.Main) {
                val currentSettings = _uiState.value.settingsValues.toMutableMap()
                currentSettings[normalizedKey] = value
                _uiState.value = _uiState.value.copy(
                    settingsValues = currentSettings,
                    lastActionMessage = if (ok) "Setting saved." else "Setting save failed.",
                )
            }
        }
    }

    fun loadLibrarySetting(key: String, defaultValue: String = "") {
        val normalizedKey = key.trim()
        if (normalizedKey.isBlank()) {
            _uiState.value = _uiState.value.copy(errorMessage = "Setting key is required.")
            return
        }
        runIoAction {
            val value = StandaloneRuntime.getSetting(normalizedKey, defaultValue)
            withContext(Dispatchers.Main) {
                val currentSettings = _uiState.value.settingsValues.toMutableMap()
                currentSettings[normalizedKey] = value
                _uiState.value = _uiState.value.copy(
                    settingsValues = currentSettings,
                    lastActionMessage = "Setting loaded.",
                )
            }
        }
    }

    fun selectImage(image: Map<String, Any>) {
        _uiState.value = _uiState.value.copy(selectedImage = image)
    }

    fun selectedImageUrl(): String? {
        val image = _uiState.value.selectedImage ?: return null
        return image["file_url"]?.toString()?.takeIf { it.isNotBlank() }
            ?: image["thumbnail_url"]?.toString()?.takeIf { it.isNotBlank() }
            ?: image["path"]?.toString()?.takeIf { it.isNotBlank() }
    }

    fun previewFileOperations(payload: Map<String, Any>) {
        runIoAction {
            val response = StandaloneRuntime.previewFileOperations(payload)
            val ok = response["ok"] as? Boolean ?: false
            val preview = response["operations"] as? List<Map<String, Any>> ?: emptyList()
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    fileOperationPreview = preview,
                    fileOperationResults = emptyList(),
                    fileOperationProgress = 0.0,
                    fileOperationRunning = false,
                    lastActionMessage = if (ok) "Prepared ${preview.size} operation(s)." else (response["message"]?.toString() ?: "Preview failed."),
                )
            }
        }
    }

    fun executeFileOperations(payload: Map<String, Any>) {
        runIoAction {
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    fileOperationRunning = true,
                    fileOperationProgress = 0.0,
                    lastActionMessage = "Executing file operations...",
                )
            }
            val response = StandaloneRuntime.executeFileOperations(payload)
            val results = response["results"] as? List<Map<String, Any>> ?: emptyList()
            val undoAvailable = response["undo_available"] as? Boolean ?: false
            val ok = response["ok"] as? Boolean ?: false
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    fileOperationResults = results,
                    fileOperationProgress = if (results.isEmpty()) 0.0 else 1.0,
                    fileOperationRunning = false,
                    fileOperationUndoAvailable = undoAvailable,
                    lastActionMessage = if (ok) "Executed ${results.size} operation(s)." else (response["message"]?.toString() ?: "Execution failed."),
                    selectedImage = if (ok) _uiState.value.selectedImage else _uiState.value.selectedImage,
                    searchResults = _uiState.value.searchResults,
                    totalResults = _uiState.value.totalResults,
                )
            }
            if (ok) {
                applyFileOperationResultsToUi(payload, results)
            }
        }
    }

    fun executeFileOperationSequence(payloads: List<Map<String, Any>>) {
        if (payloads.isEmpty()) {
            return
        }
        runIoAction {
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    fileOperationRunning = true,
                    fileOperationProgress = 0.0,
                    lastActionMessage = "Executing file operations...",
                )
            }

            val mergedResults = mutableListOf<Map<String, Any>>()
            var overallOk = true
            var undoAvailable = false

            for (payload in payloads) {
                val response = StandaloneRuntime.executeFileOperations(payload)
                val results = response["results"] as? List<Map<String, Any>> ?: emptyList()
                val ok = response["ok"] as? Boolean ?: false
                mergedResults += results
                overallOk = overallOk && ok
                if (response["undo_available"] as? Boolean == true) {
                    undoAvailable = true
                }
                if (ok) {
                    applyFileOperationResultsToUi(payload, results)
                }
                if (!ok) {
                    break
                }
            }

            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    fileOperationResults = mergedResults,
                    fileOperationProgress = if (mergedResults.isEmpty()) 0.0 else 1.0,
                    fileOperationRunning = false,
                    fileOperationUndoAvailable = undoAvailable,
                    lastActionMessage = if (overallOk) {
                        "Executed ${mergedResults.size} operation(s)."
                    } else {
                        "Execution failed."
                    },
                    selectedImage = _uiState.value.selectedImage,
                    searchResults = _uiState.value.searchResults,
                    totalResults = _uiState.value.totalResults,
                )
            }

            if (overallOk) {
                // State has already been updated incrementally per operation.
            }
        }
    }

    fun undoLastFileOperations() {
        runIoAction {
            val response = StandaloneRuntime.undoLastFileOperations()
            val results = response["results"] as? List<Map<String, Any>> ?: emptyList()
            val ok = response["ok"] as? Boolean ?: false
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    fileOperationResults = results,
                    fileOperationUndoAvailable = false,
                    lastActionMessage = if (ok) "Undo executed (${results.size} operation(s))." else (response["message"]?.toString() ?: "Undo failed."),
                    selectedImage = _uiState.value.selectedImage,
                    searchResults = _uiState.value.searchResults,
                    totalResults = _uiState.value.totalResults,
                )
            }
            if (ok) {
                applyGroupedFileOperationResultsToUi(results)
            }
        }
    }

    private suspend fun applyGroupedFileOperationResultsToUi(results: List<Map<String, Any>>) {
        val successful = results.filter { it["ok"] == true }
        if (successful.isEmpty()) {
            return
        }
        val grouped = successful.groupBy { it["action"]?.toString()?.trim()?.lowercase().orEmpty() }
        grouped.forEach { (action, rows) ->
            if (action.isBlank()) {
                return@forEach
            }
            applyFileOperationResultsToUi(mapOf("action" to action), rows)
        }
    }

    private suspend fun applyFileOperationResultsToUi(payload: Map<String, Any>, results: List<Map<String, Any>>) {
        val successful = results.filter { it["ok"] == true }
        if (successful.isEmpty()) {
            return
        }

        val action = payload["action"]?.toString()?.trim()?.lowercase().orEmpty()
        when (action) {
            "rename_image", "batch_rename_images", "move_images", "batch_move" -> {
                val totalStart = SystemClock.elapsedRealtime()
                val operationName = when (action) {
                    "rename_image", "batch_rename_images" -> "rename"
                    else -> "move"
                }
                val ids = successful.mapNotNull { (it["image_id"] as? Number)?.toInt() }.distinct()
                if (ids.isNotEmpty()) {
                    val stage9Start = SystemClock.elapsedRealtime()
                    val latestById = ids.mapNotNull { id -> StandaloneRuntime.searchByImageId(id)?.let { id to it } }.toMap()
                    val stage9Ms = SystemClock.elapsedRealtime() - stage9Start
                    withContext(Dispatchers.Main) {
                        val stage8Start = SystemClock.elapsedRealtime()
                        val current = _uiState.value
                        val images = current.images.toMutableList()
                        val search = current.searchResults.toMutableList()
                        for ((id, latestRow) in latestById) {
                            val imageIndex = images.indexOfFirst { row -> row["image_id"].asIntOrZero() == id }
                            if (imageIndex >= 0) {
                                images[imageIndex] = latestRow
                            }
                            if (search.isNotEmpty()) {
                                val searchIndex = search.indexOfFirst { row -> row["image_id"].asIntOrZero() == id }
                                if (searchIndex >= 0) {
                                    search[searchIndex] = latestRow
                                }
                            }
                        }
                        _uiState.value = current.copy(
                            images = images,
                            searchResults = search,
                            totalResults = if (search.isEmpty()) current.totalResults else search.size,
                        )
                        val stage8Ms = SystemClock.elapsedRealtime() - stage8Start
                        val totalMs = SystemClock.elapsedRealtime() - totalStart
                        Log.d(FILE_OP_TIMING_TAG, "$operationName stage8_ui_refresh_ms=$stage8Ms")
                        Log.d(FILE_OP_TIMING_TAG, "$operationName stage9_post_processing_ms=$stage9Ms")
                        Log.d(FILE_OP_TIMING_TAG, "$operationName stage1to9_total_ms=$totalMs")
                    }
                }
            }
            "copy_images", "batch_copy" -> {
                val copiedIds = successful.mapNotNull { (it["copied_image_id"] as? Number)?.toInt() }
                    .filter { it > 0 }
                    .distinct()
                if (copiedIds.isNotEmpty()) {
                    val copiedRows = copiedIds.mapNotNull { StandaloneRuntime.searchByImageId(it) }
                    withContext(Dispatchers.Main) {
                        val current = _uiState.value
                        val existingIds = current.images.map { it["image_id"].asIntOrZero() }.toSet()
                        val toAdd = copiedRows.filter { it["image_id"].asIntOrZero() !in existingIds }
                        _uiState.value = current.copy(
                            images = current.images + toAdd,
                            searchResults = if (current.searchResults.isEmpty()) current.searchResults else current.searchResults + toAdd,
                            totalResults = if (current.searchResults.isEmpty()) current.totalResults else current.searchResults.size + toAdd.size,
                        )
                    }
                }
            }
            "delete_images", "batch_delete" -> {
                val deletedIds = successful.mapNotNull { (it["image_id"] as? Number)?.toInt() }.distinct().toSet()
                if (deletedIds.isNotEmpty()) {
                    withContext(Dispatchers.Main) {
                        val current = _uiState.value
                        val images = current.images.filter { it["image_id"].asIntOrZero() !in deletedIds }
                        val search = current.searchResults.filter { it["image_id"].asIntOrZero() !in deletedIds }
                        val selected = current.selectedImage?.takeIf { it["image_id"].asIntOrZero() !in deletedIds }
                        _uiState.value = current.copy(
                            images = images,
                            searchResults = search,
                            selectedImage = selected,
                            totalResults = if (search.isEmpty()) current.totalResults else search.size,
                        )
                    }
                }
            }
            "rename_folder", "create_folder", "delete_folder" -> {
                applyFolderOperationResultsToUi(action, successful)
            }
        }
    }

    private suspend fun applyFolderOperationResultsToUi(action: String, results: List<Map<String, Any>>) {
        withContext(Dispatchers.Main) {
            val current = _uiState.value
            var folders = current.libraryFolders
            when (action) {
                "rename_folder" -> {
                    val replacements = results.mapNotNull { row ->
                        val oldUri = row["old_uri"]?.toString()?.trim().orEmpty()
                        val newUri = row["new_uri"]?.toString()?.trim().orEmpty()
                        if (oldUri.isBlank() || newUri.isBlank()) null else oldUri to newUri
                    }
                    if (replacements.isNotEmpty()) {
                        val replacementMap = replacements.toMap()
                        folders = folders.map { folder ->
                            val oldUri = folder["folder_uri"]?.toString().orEmpty()
                            val newUri = replacementMap[oldUri] ?: return@map folder
                            folder + mapOf("folder_uri" to newUri)
                        }
                    }
                }
                "create_folder" -> {
                    val existingUris = folders.mapNotNull { it["folder_uri"]?.toString() }.toSet()
                    val toAdd = results.mapNotNull { row ->
                        val uri = row["folder_uri"]?.toString()?.trim().orEmpty()
                        if (uri.isBlank() || uri in existingUris) {
                            null
                        } else {
                            mapOf(
                                "folder_uri" to uri,
                                "enabled" to true,
                                "added_at_ms" to System.currentTimeMillis(),
                                "last_scan_started_ms" to 0L,
                                "last_scan_completed_ms" to 0L,
                                "last_scan_status" to "",
                                "last_scan_count" to 0,
                            )
                        }
                    }
                    if (toAdd.isNotEmpty()) {
                        folders = folders + toAdd
                    }
                }
                "delete_folder" -> {
                    val removed = results.mapNotNull { it["folder_uri"]?.toString()?.trim() }
                        .filter { it.isNotBlank() }
                        .toSet()
                    if (removed.isNotEmpty()) {
                        folders = folders.filterNot { (it["folder_uri"]?.toString().orEmpty()) in removed }
                    }
                }
            }

            _uiState.value = current.copy(
                libraryFolders = folders,
                stats = current.stats + mapOf(
                    "total_folders" to folders.size,
                ),
            )
        }
    }

    fun clearFileOperationPreview() {
        _uiState.value = _uiState.value.copy(
            fileOperationPreview = emptyList(),
            fileOperationResults = emptyList(),
            fileOperationProgress = 0.0,
            fileOperationRunning = false,
        )
    }

    fun approveReview(itemId: String) {
        submitReviewAction(itemId, "approve")
    }

    fun rejectReview(itemId: String) {
        submitReviewAction(itemId, "reject")
    }

    fun undoReview(itemId: String) {
        submitReviewAction(itemId, "undo")
    }

    override fun onCleared() {
        scanPollingJob?.cancel()
        super.onCleared()
    }

    private fun ensureScanPolling() {
        if (scanPollingJob?.isActive == true) {
            return
        }
        scanPollingJob = viewModelScope.launch(Dispatchers.IO) {
            while (true) {
                val state = _uiState.value.scanStatus
                if (state !in setOf("running", "paused", "queued", "in_progress")) {
                    break
                }
                updateScanState()
                delay(1200)
            }
        }
    }

    private suspend fun updateScanState() {
        try {
            val status = StandaloneRuntime.scanStatus()
            val state = status["status"]?.toString()?.ifBlank { "idle" } ?: "idle"
            val progress = status["progress"].asDoubleOrZero()
            val discovered = status["discovered_images"].asIntOrZero()

            val shouldRefreshData = state == "completed"
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(
                    scanStatus = state,
                    scanProgress = progress,
                    scanDiscoveredImages = discovered,
                    errorMessage = status["error"]?.toString(),
                )
            }

            if (shouldRefreshData) {
                refreshDashboard()
            }
        } catch (t: Throwable) {
            withContext(Dispatchers.Main) {
                _uiState.value = _uiState.value.copy(errorMessage = t.message ?: t.javaClass.simpleName)
            }
        }
    }

    private fun Any?.asDoubleOrZero(): Double = when (this) {
        is Number -> this.toDouble()
        is String -> this.toDoubleOrNull() ?: 0.0
        else -> 0.0
    }

    private fun Any?.asIntOrZero(): Int = when (this) {
        is Number -> this.toInt()
        is String -> this.toIntOrNull() ?: 0
        else -> 0
    }

    private fun updateImageState(imageId: Int, update: (Map<String, Any>) -> Map<String, Any>): Map<String, Any>? {
        val current = _uiState.value
        var updatedImage: Map<String, Any>? = null
        val updatedImages = current.images.map { image ->
            if (image["image_id"].asIntOrZero() == imageId) {
                val next = update(image)
                if (updatedImage == null) {
                    updatedImage = next
                }
                next
            } else {
                image
            }
        }
        val updatedSearchResults = current.searchResults.map { image ->
            if (image["image_id"].asIntOrZero() == imageId) {
                update(image)
            } else {
                image
            }
        }
        val updatedSelected = current.selectedImage?.let { image ->
            if (image["image_id"].asIntOrZero() == imageId) {
                update(image)
            } else {
                image
            }
        }
        _uiState.value = current.copy(
            images = updatedImages,
            searchResults = updatedSearchResults,
            selectedImage = updatedSelected,
        )
        return updatedImage
    }

    private fun submitReviewAction(itemId: String, action: String) {
        runIoAction {
            StandaloneRuntime.updateReview(itemId = itemId, action = action)
            refreshDashboard()
        }
    }

    private suspend fun refreshImageInState(imageId: Int, fallback: Map<String, Any>? = null) {
        val latestFromRepo = StandaloneRuntime.searchByImageId(imageId)
        Log.d(
            VM_TRACE_TAG,
            "ViewModel immediate SELECT result: imageId=$imageId repo=${imageSummary(latestFromRepo)} fallback=${imageSummary(fallback)}",
        )
        val latest = latestFromRepo ?: fallback ?: return
        withContext(Dispatchers.Main) {
            val current = _uiState.value
            Log.d(VM_TRACE_TAG, "selectedImage before replacement: imageId=$imageId value=${imageSummary(current.selectedImage)}")
            val updatedImages = current.images.map { image ->
                if (image["image_id"].asIntOrZero() == imageId) latest else image
            }
            val updatedSearchResults = current.searchResults.map { image ->
                if (image["image_id"].asIntOrZero() == imageId) latest else image
            }
            val updatedSelected = current.selectedImage?.let { image ->
                if (image["image_id"].asIntOrZero() == imageId) latest else image
            }
            _uiState.value = current.copy(
                images = updatedImages,
                searchResults = updatedSearchResults,
                selectedImage = updatedSelected,
            )
            Log.d(VM_TRACE_TAG, "selectedImage after replacement: imageId=$imageId value=${imageSummary(updatedSelected)}")
            Log.d(VM_TRACE_TAG, "ViewModel state updated: imageId=$imageId")
        }
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

    private fun runIoAction(block: suspend () -> Unit) {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                block()
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    _uiState.value = _uiState.value.copy(errorMessage = t.message ?: t.javaClass.simpleName)
                }
            }
        }
    }
}