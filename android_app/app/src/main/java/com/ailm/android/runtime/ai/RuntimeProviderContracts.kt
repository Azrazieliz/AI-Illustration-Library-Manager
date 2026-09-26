package com.ailm.android.runtime.ai

import android.os.Build
import java.util.concurrent.ConcurrentHashMap

enum class AiRuntimeProviderState {
    AVAILABLE,
    UNAVAILABLE,
    INITIALIZING,
    FAILED,
    UNSUPPORTED,
}

data class AiRuntimeProviderCapabilities(
    val providerId: String,
    val backendName: String,
    val runtimeType: AiRuntimeType,
    val supportedFormats: Set<String>,
    val supportedTasks: Set<String>,
    val supportedPrecisions: Set<String>,
    val supportedDevices: Set<String>,
    val supportedDelegates: Set<String>,
    val supportedQuantizations: Set<String>,
    val supportedTensorLayouts: Set<String>,
    val supportedInputTypes: Set<String>,
    val supportedOutputTypes: Set<String>,
    val maximumContext: Int,
    val maximumImageResolution: Int,
    val runtimeVersion: String,
    val abiCompatible: Boolean,
    val androidApiCompatible: Boolean,
    val metadata: Map<String, Any> = emptyMap(),
)

data class AiRuntimeProviderHealth(
    val state: AiRuntimeProviderState,
    val message: String,
    val memoryBytes: Long,
    val metadata: Map<String, Any> = emptyMap(),
)

data class AiRuntimeModelHandle(
    val modelId: String,
    val version: String,
    val providerId: String,
    val metadata: Map<String, Any> = emptyMap(),
)

interface ModelAwareAiBackend {
    fun supportsModel(model: AiModelDescriptor): Boolean
}

interface AiRuntimeProvider : AiBackendRuntime, ModelAwareAiBackend {
    val providerState: AiRuntimeProviderState

    fun initializeProvider(): AiRuntimeProviderState
    suspend fun loadModel(model: AiModelDescriptor): AiRuntimeModelHandle?
    suspend fun unloadModel(handle: AiRuntimeModelHandle): Boolean
    override suspend fun execute(request: AiExecutionRequest, reporter: AiProgressReporter): AiExecutionResult
    suspend fun cancel(sessionId: String): Boolean
    suspend fun release(): Boolean
    fun queryCapabilities(): AiRuntimeProviderCapabilities
    fun queryMemory(): Map<String, Any>
    suspend fun benchmark(model: AiModelDescriptor): Map<String, Any>
    suspend fun health(): AiRuntimeProviderHealth
}

interface NativeRuntimePlugin {
    val runtimeType: AiRuntimeType
    val libraryName: String

    fun probe(): AiRuntimeProviderHealth
    fun queryCapabilities(): AiRuntimeProviderCapabilities
    suspend fun loadModel(model: AiModelDescriptor): AiRuntimeModelHandle?
    suspend fun unloadModel(handle: AiRuntimeModelHandle): Boolean
    suspend fun execute(request: AiExecutionRequest, reporter: AiProgressReporter): AiExecutionResult
    suspend fun cancel(sessionId: String): Boolean
    suspend fun release(): Boolean
    fun queryMemory(): Map<String, Any>
    suspend fun benchmark(model: AiModelDescriptor): Map<String, Any>
}

object NativeRuntimePluginRegistry {
    private val plugins = ConcurrentHashMap<AiRuntimeType, NativeRuntimePlugin>()

    fun register(plugin: NativeRuntimePlugin) {
        plugins[plugin.runtimeType] = plugin
    }

    fun unregister(runtimeType: AiRuntimeType): Boolean = plugins.remove(runtimeType) != null

    fun resolve(runtimeType: AiRuntimeType): NativeRuntimePlugin? = plugins[runtimeType]
}

abstract class BaseAiRuntimeProvider : AiRuntimeProvider {
    @Volatile
    final override var providerState: AiRuntimeProviderState = AiRuntimeProviderState.INITIALIZING
        protected set

    @Volatile
    protected var providerMessage: String = "Initializing"

    override fun supportsModel(model: AiModelDescriptor): Boolean {
        val capabilities = queryCapabilities()
        if (providerState != AiRuntimeProviderState.AVAILABLE || !FileSupport.isModelFile(model)) return false
        if (ModelInferenceContract.validationIssues(model).isNotEmpty()) return false
        if (model.supportedTasks.isNotEmpty() && model.supportedTasks.none { task ->
                AiTaskTypes.normalize(task) in capabilities.supportedTasks.map(AiTaskTypes::normalize)
            }
        ) return false
        val format = FileSupport.modelFormat(model)
        return capabilities.supportedFormats.isEmpty() || format in capabilities.supportedFormats
    }

    override fun detectCapabilities(): AiBackendCapability {
        val capabilities = queryCapabilities()
        return AiBackendCapability(
            runtimeId = runtimeId,
            runtimeType = runtimeType,
            supportedTasks = if (providerState == AiRuntimeProviderState.AVAILABLE) capabilities.supportedTasks else emptySet(),
            supportsCancellation = true,
            supportsPauseResume = false,
            maxConcurrentTasks = 1,
            metadata = capabilities.metadata + mapOf(
                "provider_state" to providerState.name.lowercase(),
                "provider_message" to providerMessage,
                "runtime_version" to capabilities.runtimeVersion,
                "supported_formats" to capabilities.supportedFormats.sorted(),
                "supported_devices" to capabilities.supportedDevices.sorted(),
                "supported_delegates" to capabilities.supportedDelegates.sorted(),
            ),
        )
    }

    override suspend fun requestCancellation(sessionId: String): Boolean = cancel(sessionId)
}

internal object FileSupport {
    fun isModelFile(model: AiModelDescriptor): Boolean = model.installed && model.installPath.isNotBlank() && java.io.File(model.installPath).isFile

    fun modelFormat(model: AiModelDescriptor): String {
        val explicit = model.metadata["model_format"]?.toString()?.trim()?.lowercase().orEmpty()
        if (explicit.isNotBlank()) return explicit
        return model.installPath.substringAfterLast('.', "").trim().lowercase()
    }

    fun currentAbiCompatible(): Boolean = Build.SUPPORTED_ABIS?.isNotEmpty() == true
    fun currentApiCompatible(): Boolean = Build.VERSION.SDK_INT >= 30
}