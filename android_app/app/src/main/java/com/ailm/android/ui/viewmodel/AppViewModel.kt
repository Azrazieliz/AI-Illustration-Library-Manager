package com.ailm.android.ui.viewmodel

import android.content.Context
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
    val collections: List<Map<String, Any>> = emptyList(),
    val downloads: List<Map<String, Any>> = emptyList(),
    val knowledgePacks: List<Map<String, Any>> = emptyList(),
    val reviewQueue: List<Map<String, Any>> = emptyList(),
    val tags: List<String> = emptyList(),
    val selectedLibraryUri: String = "",
    val scanStatus: String = "idle",
    val scanProgress: Double = 0.0,
    val scanDiscoveredImages: Int = 0,
    val selectedImage: Map<String, Any>? = null,
    val firstLaunchCompleted: Boolean = false,
    val errorMessage: String? = null,
)

class AppViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(AppUiState())
    val uiState: StateFlow<AppUiState> = _uiState.asStateFlow()
    private var scanPollingJob: Job? = null

    fun initializeConfiguration(context: Context, libraryUri: String) {
        StandaloneRuntime.initialize(context.applicationContext)
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
                val images = StandaloneRuntime.getLibraryImages(pageSize = 250)
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
                        collections = collections,
                        downloads = downloads,
                        knowledgePacks = knowledgePacks,
                        reviewQueue = reviewQueue,
                        tags = tags,
                        selectedLibraryUri = current.selectedLibraryUri,
                        scanStatus = current.scanStatus,
                        scanProgress = current.scanProgress,
                        scanDiscoveredImages = current.scanDiscoveredImages,
                        selectedImage = current.selectedImage,
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
                    _uiState.value = _uiState.value.copy(scanStatus = "running", errorMessage = null)
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

    fun selectImage(image: Map<String, Any>) {
        _uiState.value = _uiState.value.copy(selectedImage = image)
    }

    fun selectedImageUrl(): String? {
        val image = _uiState.value.selectedImage ?: return null
        return image["file_url"]?.toString()?.takeIf { it.isNotBlank() }
            ?: image["thumbnail_url"]?.toString()?.takeIf { it.isNotBlank() }
            ?: image["path"]?.toString()?.takeIf { it.isNotBlank() }
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

    private fun submitReviewAction(itemId: String, action: String) {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                StandaloneRuntime.updateReview(itemId = itemId, action = action)
                refreshDashboard()
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    _uiState.value = _uiState.value.copy(errorMessage = t.message ?: t.javaClass.simpleName)
                }
            }
        }
    }
}