package com.ailm.android.runtime.ai

import java.util.Locale

enum class AiRuntimeType(val raw: String) {
    ONNX("onnx"),
    LLAMA_CPP("llama_cpp"),
    TFLITE("tflite"),
    NCNN("ncnn"),
    MNN("mnn"),
    CUSTOM("custom");

    companion object {
        fun fromRaw(raw: String): AiRuntimeType {
            val normalized = raw.trim().lowercase()
            return entries.firstOrNull { it.raw == normalized } ?: CUSTOM
        }
    }
}

object AiTaskTypes {
    val EXECUTION_TASKS: Set<String> = setOf(
        "ocr",
        "captioning",
        "character_recognition",
        "series_recognition",
        "tag_prediction",
        "artist_recognition",
        "embedding_generation",
        "similarity_search",
        "prompt_generation",
        "metadata_extraction",
        "duplicate_detection",
        "classification",
        "detection",
        "face_feature_extraction",
        "knowledge_pack_execution",
    )

    val INFRASTRUCTURE_TASKS: Set<String> = setOf(
        "install_model",
        "verify_model",
        "remove_model",
        "download_registration",
        "metadata_refresh",
        "runtime_probe",
        "health_check",
    )

    val ALL_SUPPORTED_TASKS: Set<String> = EXECUTION_TASKS + INFRASTRUCTURE_TASKS

    private val aliases: Map<String, String> = mapOf(
        "caption" to "captioning",
        "image captioning" to "captioning",
        "character recognition" to "character_recognition",
        "series recognition" to "series_recognition",
        "tag prediction" to "tag_prediction",
        "artist recognition" to "artist_recognition",
        "embedding generation" to "embedding_generation",
        "similarity search" to "similarity_search",
        "prompt generation" to "prompt_generation",
        "metadata extraction" to "metadata_extraction",
        "duplicate detection" to "duplicate_detection",
        "image classification" to "classification",
        "object detection" to "detection",
        "face extraction" to "face_feature_extraction",
        "face feature extraction" to "face_feature_extraction",
        "knowledge pack execution" to "knowledge_pack_execution",
    )

    fun normalize(raw: String): String {
        val compact = raw
            .trim()
            .lowercase(Locale.US)
            .replace('-', '_')
            .replace(' ', '_')
            .replace(Regex("_+"), "_")
        return aliases[compact.replace('_', ' ')]
            ?: aliases[compact]
            ?: compact
    }

    fun isSupported(raw: String): Boolean {
        return normalize(raw) in ALL_SUPPORTED_TASKS
    }

    fun isExecutionTask(raw: String): Boolean {
        return normalize(raw) in EXECUTION_TASKS
    }

    fun isInfrastructureTask(raw: String): Boolean {
        return normalize(raw) in INFRASTRUCTURE_TASKS
    }
}

data class AiHardwareProfile(
    val cpuCores: Int,
    val gpuAvailable: Boolean,
    val npuAvailable: Boolean,
    val totalRamBytes: Long,
    val availableRamBytes: Long,
    val totalStorageBytes: Long,
    val availableStorageBytes: Long,
    val threadCount: Int,
    val simdFeatures: List<String>,
    val abiList: List<String>,
    val capturedAtMs: Long,
) {
    fun toMap(): Map<String, Any> {
        return mapOf(
            "cpu_cores" to cpuCores,
            "gpu_available" to gpuAvailable,
            "npu_available" to npuAvailable,
            "total_ram_bytes" to totalRamBytes,
            "available_ram_bytes" to availableRamBytes,
            "total_storage_bytes" to totalStorageBytes,
            "available_storage_bytes" to availableStorageBytes,
            "thread_count" to threadCount,
            "simd_features" to simdFeatures,
            "abi_list" to abiList,
            "captured_at_ms" to capturedAtMs,
        )
    }
}

data class AiModelDescriptor(
    val modelId: String,
    val version: String,
    val displayName: String,
    val sizeBytes: Long,
    val hashSha256: String,
    val supportedTasks: List<String>,
    val requiredRuntime: String,
    val supportedRuntimes: List<String>,
    val dependencies: List<String>,
    val requiredHardware: Map<String, Any>,
    val compatibility: Map<String, Any>,
    val metadata: Map<String, Any>,
    val source: String,
    val sourceUri: String,
    val installed: Boolean,
    val installState: String,
    val installPath: String,
    val createdAtMs: Long,
    val updatedAtMs: Long,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "model_id" to modelId,
            "version" to version,
            "display_name" to displayName,
            "size_bytes" to sizeBytes,
            "hash_sha256" to hashSha256,
            "supported_tasks" to supportedTasks,
            "required_runtime" to requiredRuntime,
            "supported_runtimes" to supportedRuntimes,
            "dependencies" to dependencies,
            "required_hardware" to requiredHardware,
            "compatibility" to compatibility,
            "metadata" to metadata,
            "source" to source,
            "source_uri" to sourceUri,
            "installed" to installed,
            "install_state" to installState,
            "install_path" to installPath,
            "created_at_ms" to createdAtMs,
            "updated_at_ms" to updatedAtMs,
        )
    }
}

data class AiInstallRunRecord(
    val installId: String,
    val modelId: String,
    val version: String,
    val action: String,
    val sourceUri: String,
    val expectedHash: String,
    val actualHash: String,
    val status: String,
    val details: Map<String, Any>,
    val retryCount: Int,
    val createdAtMs: Long,
    val startedAtMs: Long,
    val finishedAtMs: Long,
    val errorMessage: String,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "install_id" to installId,
            "model_id" to modelId,
            "version" to version,
            "action" to action,
            "source_uri" to sourceUri,
            "expected_hash" to expectedHash,
            "actual_hash" to actualHash,
            "status" to status,
            "details" to details,
            "retry_count" to retryCount,
            "created_at_ms" to createdAtMs,
            "started_at_ms" to startedAtMs,
            "finished_at_ms" to finishedAtMs,
            "error_message" to errorMessage,
        )
    }
}

data class AiTaskRecord(
    val taskId: String,
    val taskType: String,
    val modelId: String,
    val version: String,
    val runtimeHint: String,
    val priority: Int,
    val status: String,
    val progress: Double,
    val retryCount: Int,
    val maxRetries: Int,
    val cancellationRequested: Boolean,
    val pauseRequested: Boolean,
    val dependencyTaskIds: List<String>,
    val nextRunAtMs: Long,
    val timeoutMs: Long,
    val payload: Map<String, Any>,
    val result: Map<String, Any>,
    val createdAtMs: Long,
    val updatedAtMs: Long,
    val startedAtMs: Long,
    val finishedAtMs: Long,
    val errorMessage: String,
    val sessionId: String,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "task_id" to taskId,
            "task_type" to taskType,
            "model_id" to modelId,
            "version" to version,
            "runtime_hint" to runtimeHint,
            "priority" to priority,
            "status" to status,
            "progress" to progress,
            "retry_count" to retryCount,
            "max_retries" to maxRetries,
            "cancellation_requested" to cancellationRequested,
            "pause_requested" to pauseRequested,
            "dependency_task_ids" to dependencyTaskIds,
            "next_run_at_ms" to nextRunAtMs,
            "timeout_ms" to timeoutMs,
            "payload" to payload,
            "result" to result,
            "created_at_ms" to createdAtMs,
            "updated_at_ms" to updatedAtMs,
            "started_at_ms" to startedAtMs,
            "finished_at_ms" to finishedAtMs,
            "error_message" to errorMessage,
            "session_id" to sessionId,
        )
    }
}

data class AiCacheEntry(
    val cacheKey: String,
    val modelId: String,
    val artifactPath: String,
    val sizeBytes: Long,
    val pinned: Boolean,
    val metadata: Map<String, Any>,
    val createdAtMs: Long,
    val lastAccessMs: Long,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "cache_key" to cacheKey,
            "model_id" to modelId,
            "artifact_path" to artifactPath,
            "size_bytes" to sizeBytes,
            "pinned" to pinned,
            "metadata" to metadata,
            "created_at_ms" to createdAtMs,
            "last_access_ms" to lastAccessMs,
        )
    }
}

data class AiSettings(
    val maxCacheBytes: Long = 2L * 1024L * 1024L * 1024L,
    val maxQueueRetries: Int = 3,
    val maxConcurrentTasks: Int = 1,
    val autoUpdateModels: Boolean = false,
    val allowCellularDownloads: Boolean = false,
    val preferredRuntimeOrder: List<String> = emptyList(),
    val defaultTaskTimeoutMs: Long = 15L * 60L * 1000L,
    val maxReservedRamBytes: Long = 0L,
    val schedulerPollIntervalMs: Long = 250L,
    val schedulerIdleDelayMs: Long = 500L,
    val extra: Map<String, Any> = emptyMap(),
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "max_cache_bytes" to maxCacheBytes,
            "max_queue_retries" to maxQueueRetries,
            "max_concurrent_tasks" to maxConcurrentTasks,
            "auto_update_models" to autoUpdateModels,
            "allow_cellular_downloads" to allowCellularDownloads,
            "preferred_runtime_order" to preferredRuntimeOrder,
            "default_task_timeout_ms" to defaultTaskTimeoutMs,
            "max_reserved_ram_bytes" to maxReservedRamBytes,
            "scheduler_poll_interval_ms" to schedulerPollIntervalMs,
            "scheduler_idle_delay_ms" to schedulerIdleDelayMs,
            "extra" to extra,
        )
    }
}

data class AiPluginDescriptor(
    val pluginId: String,
    val version: String,
    val displayName: String,
    val enabled: Boolean,
    val capabilities: List<String>,
    val metadata: Map<String, Any>,
    val registeredAtMs: Long,
    val updatedAtMs: Long,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "plugin_id" to pluginId,
            "version" to version,
            "display_name" to displayName,
            "enabled" to enabled,
            "capabilities" to capabilities,
            "metadata" to metadata,
            "registered_at_ms" to registeredAtMs,
            "updated_at_ms" to updatedAtMs,
        )
    }
}

data class AiCapabilityDescriptor(
    val capabilityId: String,
    val providerId: String,
    val capabilityType: String,
    val status: String,
    val metadata: Map<String, Any>,
    val registeredAtMs: Long,
    val updatedAtMs: Long,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "capability_id" to capabilityId,
            "provider_id" to providerId,
            "capability_type" to capabilityType,
            "status" to status,
            "metadata" to metadata,
            "registered_at_ms" to registeredAtMs,
            "updated_at_ms" to updatedAtMs,
        )
    }
}

data class AiExecutionRequest(
    val sessionId: String,
    val taskId: String,
    val taskType: String,
    val modelId: String,
    val version: String,
    val runtimeHint: String,
    val attempt: Int,
    val deadlineAtMs: Long,
    val payload: Map<String, Any>,
)

data class AiExecutionContext(
    val request: AiExecutionRequest,
    val task: AiTaskRecord,
    val model: AiModelDescriptor?,
    val runtimeId: String,
    val runtimeType: AiRuntimeType,
    val backendId: String,
    val reservationBytes: Long,
    val startedAtMs: Long,
    val metadata: Map<String, Any>,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "request" to mapOf(
                "session_id" to request.sessionId,
                "task_id" to request.taskId,
                "task_type" to request.taskType,
                "model_id" to request.modelId,
                "version" to request.version,
                "runtime_hint" to request.runtimeHint,
                "attempt" to request.attempt,
                "deadline_at_ms" to request.deadlineAtMs,
            ),
            "runtime_id" to runtimeId,
            "runtime_type" to runtimeType.raw,
            "backend_id" to backendId,
            "reservation_bytes" to reservationBytes,
            "started_at_ms" to startedAtMs,
            "model" to (model?.toMap() ?: emptyMap<String, Any>()),
            "metadata" to metadata,
        )
    }
}

data class AiExecutionSessionRecord(
    val sessionId: String,
    val taskId: String,
    val taskType: String,
    val modelId: String,
    val version: String,
    val runtimeId: String,
    val backendId: String,
    val status: String,
    val progress: Double,
    val retryCount: Int,
    val reservationBytes: Long,
    val context: Map<String, Any>,
    val result: Map<String, Any>,
    val createdAtMs: Long,
    val updatedAtMs: Long,
    val startedAtMs: Long,
    val finishedAtMs: Long,
    val errorMessage: String,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "session_id" to sessionId,
            "task_id" to taskId,
            "task_type" to taskType,
            "model_id" to modelId,
            "version" to version,
            "runtime_id" to runtimeId,
            "backend_id" to backendId,
            "status" to status,
            "progress" to progress,
            "retry_count" to retryCount,
            "reservation_bytes" to reservationBytes,
            "context" to context,
            "result" to result,
            "created_at_ms" to createdAtMs,
            "updated_at_ms" to updatedAtMs,
            "started_at_ms" to startedAtMs,
            "finished_at_ms" to finishedAtMs,
            "error_message" to errorMessage,
        )
    }
}

data class AiExecutionEventRecord(
    val eventId: Long,
    val sessionId: String,
    val taskId: String,
    val eventType: String,
    val message: String,
    val progress: Double,
    val payload: Map<String, Any>,
    val createdAtMs: Long,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "event_id" to eventId,
            "session_id" to sessionId,
            "task_id" to taskId,
            "event_type" to eventType,
            "message" to message,
            "progress" to progress,
            "payload" to payload,
            "created_at_ms" to createdAtMs,
        )
    }
}

data class AiRuntimeHealthSnapshot(
    val snapshotId: Long,
    val runtimeId: String,
    val backendId: String,
    val status: String,
    val healthy: Boolean,
    val latencyMs: Long,
    val metadata: Map<String, Any>,
    val capturedAtMs: Long,
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "snapshot_id" to snapshotId,
            "runtime_id" to runtimeId,
            "backend_id" to backendId,
            "status" to status,
            "healthy" to healthy,
            "latency_ms" to latencyMs,
            "metadata" to metadata,
            "captured_at_ms" to capturedAtMs,
        )
    }
}

data class AiBackendCapability(
    val runtimeId: String,
    val runtimeType: AiRuntimeType,
    val supportedTasks: Set<String>,
    val supportsCancellation: Boolean,
    val supportsPauseResume: Boolean,
    val maxConcurrentTasks: Int,
    val metadata: Map<String, Any> = emptyMap(),
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "runtime_id" to runtimeId,
            "runtime_type" to runtimeType.raw,
            "supported_tasks" to supportedTasks.sorted(),
            "supports_cancellation" to supportsCancellation,
            "supports_pause_resume" to supportsPauseResume,
            "max_concurrent_tasks" to maxConcurrentTasks,
            "metadata" to metadata,
        )
    }
}

data class AiBackendHealth(
    val healthy: Boolean,
    val status: String,
    val latencyMs: Long,
    val metadata: Map<String, Any> = emptyMap(),
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "healthy" to healthy,
            "status" to status,
            "latency_ms" to latencyMs,
            "metadata" to metadata,
        )
    }
}

data class AiExecutionResult(
    val ok: Boolean,
    val status: String,
    val message: String,
    val details: Map<String, Any> = emptyMap(),
)

fun interface AiProgressReporter {
    suspend fun report(progress: Double, message: String)
}

interface AiBackendRuntime {
    val runtimeId: String
    val runtimeType: AiRuntimeType
    val supportedTasks: Set<String>

    fun detectCapabilities(): AiBackendCapability {
        return AiBackendCapability(
            runtimeId = runtimeId,
            runtimeType = runtimeType,
            supportedTasks = supportedTasks,
            supportsCancellation = false,
            supportsPauseResume = false,
            maxConcurrentTasks = 1,
        )
    }

    suspend fun healthCheck(): AiBackendHealth {
        return AiBackendHealth(
            healthy = true,
            status = "ok",
            latencyMs = 0L,
        )
    }

    suspend fun requestCancellation(sessionId: String): Boolean {
        return false
    }

    suspend fun requestPause(sessionId: String): Boolean {
        return false
    }

    suspend fun requestResume(sessionId: String): Boolean {
        return false
    }

    suspend fun execute(request: AiExecutionRequest, reporter: AiProgressReporter): AiExecutionResult
}

interface LocalAiRuntimeGateway {
    suspend fun execute(
        request: AiExecutionRequest,
        backend: AiBackendRuntime,
        reporter: AiProgressReporter,
    ): AiExecutionResult
}

data class AiRetryDecision(
    val shouldRetry: Boolean,
    val nextRunAtMs: Long,
    val reason: String,
)

data class AiValidationIssue(
    val code: String,
    val message: String,
    val severity: String = "error",
)

data class AiValidationReport(
    val valid: Boolean,
    val issues: List<AiValidationIssue>,
    val metadata: Map<String, Any> = emptyMap(),
) {
    fun toMap(): Map<String, Any> {
        return linkedMapOf(
            "valid" to valid,
            "issues" to issues.map {
                mapOf(
                    "code" to it.code,
                    "message" to it.message,
                    "severity" to it.severity,
                )
            },
            "metadata" to metadata,
        )
    }
}
