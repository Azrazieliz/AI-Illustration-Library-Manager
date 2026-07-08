package com.ailm.android.ui.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

enum class FirstLaunchStep(val order: Int, val title: String) {
    Welcome(1, "Welcome"),
    ChooseLibraryFolders(2, "Choose Library Folder(s)"),
    ChooseStorageLocation(3, "Choose Storage Location"),
    ConfigureRecognitionModels(4, "Configure Recognition Models"),
    DownloadKnowledgePacks(5, "Download Knowledge Packs"),
    ChooseCacheSize(6, "Choose Cache Size"),
    RunInitialScan(7, "Run Initial Scan"),
    GenerateEmbeddings(8, "Generate Embeddings"),
    InitialRecognition(9, "Initial Recognition"),
    InitialOrganization(10, "Initial Organization"),
    Finish(11, "Finish"),
}

data class FirstLaunchState(
    val currentStep: FirstLaunchStep = FirstLaunchStep.Welcome,
    val completedSteps: Set<FirstLaunchStep> = emptySet(),
    val resumableCheckpoint: String = FirstLaunchStep.Welcome.name,
)

interface FirstLaunchStateStore {
    suspend fun save(state: FirstLaunchState)
    suspend fun restore(): FirstLaunchState
}

class InMemoryFirstLaunchStateStore : FirstLaunchStateStore {
    private var state: FirstLaunchState = FirstLaunchState()

    override suspend fun save(state: FirstLaunchState) {
        this.state = state
    }

    override suspend fun restore(): FirstLaunchState = state
}

class FirstLaunchWizardViewModel(
    private val store: FirstLaunchStateStore = InMemoryFirstLaunchStateStore(),
) : ViewModel() {
    private val _state = MutableStateFlow(FirstLaunchState())
    val state: StateFlow<FirstLaunchState> = _state.asStateFlow()

    fun restore() {
        viewModelScope.launch {
            _state.value = store.restore()
        }
    }

    fun advance() {
        val current = _state.value.currentStep
        val next = FirstLaunchStep.entries.firstOrNull { it.order == current.order + 1 } ?: FirstLaunchStep.Finish
        val updated = _state.value.copy(
            currentStep = next,
            completedSteps = _state.value.completedSteps + current,
            resumableCheckpoint = next.name,
        )
        _state.value = updated
        viewModelScope.launch {
            store.save(updated)
        }
    }
}
