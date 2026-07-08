package com.ailm.android.ui.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ailm.android.bridge.AndroidBackendBridge
import com.ailm.android.bridge.NoOpBackendBridge
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class AppUiState(
    val loading: Boolean = false,
    val health: Map<String, Any> = emptyMap(),
    val stats: Map<String, Any> = emptyMap(),
    val downloads: List<Map<String, Any>> = emptyList(),
    val knowledgePacks: List<Map<String, Any>> = emptyList(),
    val reviewQueue: List<Map<String, Any>> = emptyList(),
    val tags: List<String> = emptyList(),
)

class AppViewModel(
    private val bridge: AndroidBackendBridge = NoOpBackendBridge(),
) : ViewModel() {
    private val _uiState = MutableStateFlow(AppUiState())
    val uiState: StateFlow<AppUiState> = _uiState.asStateFlow()

    fun refreshDashboard() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(loading = true)
            _uiState.value = _uiState.value.copy(
                loading = false,
                health = bridge.healthStatus(),
                stats = bridge.libraryStatistics(),
                downloads = bridge.listDownloads(),
                knowledgePacks = bridge.listKnowledgePacks(),
                reviewQueue = bridge.getReviewQueue(),
                tags = bridge.getTags(),
            )
        }
    }

    fun approveReview(itemId: String): Boolean = bridge.updateReview(itemId = itemId, action = "approve")
    fun rejectReview(itemId: String): Boolean = bridge.updateReview(itemId = itemId, action = "reject")
    fun undoReview(itemId: String): Boolean = bridge.updateReview(itemId = itemId, action = "undo")
}
