package com.ailm.android.runtime.ai

import android.content.Context
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.sqrt

class LocalAiBackendManager {
    private val backends = ConcurrentHashMap<String, AiBackendRuntime>()

    fun registerBackend(backend: AiBackendRuntime) {
        backends[backend.runtimeId.lowercase()] = backend
    }

    fun unregisterBackend(runtimeId: String): Boolean {
        return backends.remove(runtimeId.trim().lowercase()) != null
    }

    fun clearBackends() {
        backends.clear()
    }

    fun snapshotBackends(): List<AiBackendRuntime> {
        return backends.values.sortedBy { it.runtimeId }
    }

    fun listBackends(): List<Map<String, Any>> {
        return snapshotBackends().map { backend ->
            val capability = backend.detectCapabilities()
            mapOf(
                "runtime_id" to backend.runtimeId,
                "runtime_type" to backend.runtimeType.raw,
                "supported_tasks" to capability.supportedTasks.sorted(),
                "supports_cancellation" to capability.supportsCancellation,
                "supports_pause_resume" to capability.supportsPauseResume,
                "max_concurrent_tasks" to capability.maxConcurrentTasks,
                "metadata" to capability.metadata,
            )
        }
    }

    fun hasRuntime(runtimeName: String): Boolean {
        val normalized = runtimeName.trim().lowercase()
        if (normalized.isBlank()) {
            return false
        }
        return snapshotBackends().any {
            it.runtimeId.equals(normalized, ignoreCase = true) ||
                it.runtimeType.raw.equals(normalized, ignoreCase = true)
        }
    }

    fun resolveByRuntime(runtimeName: String): List<AiBackendRuntime> {
        val normalized = runtimeName.trim().lowercase()
        if (normalized.isBlank()) {
            return snapshotBackends()
        }
        return snapshotBackends().filter {
            it.runtimeId.equals(normalized, ignoreCase = true) ||
                it.runtimeType.raw.equals(normalized, ignoreCase = true)
        }
    }
}

class LocalAiValidationService(
    private val repository: LocalAiRepository,
    private val backendManager: LocalAiBackendManager,
    private val resourceManager: LocalAiResourceManager,
) {
    fun validateModelDescriptor(model: AiModelDescriptor): AiValidationReport {
        val issues = mutableListOf<AiValidationIssue>()
        if (model.modelId.isBlank()) {
            issues += AiValidationIssue("model_id_missing", "model_id is required")
        }
        if (model.version.isBlank()) {
            issues += AiValidationIssue("model_version_missing", "version is required")
        }
        if (model.displayName.isBlank()) {
            issues += AiValidationIssue("display_name_missing", "display_name is required")
        }
        if (model.sizeBytes < 0L) {
            issues += AiValidationIssue("size_negative", "size_bytes must be non-negative")
        }
        if (model.hashSha256.isNotBlank() && !model.hashSha256.matches(Regex("^[a-fA-F0-9]{64}$"))) {
            issues += AiValidationIssue("hash_invalid", "hash_sha256 must be a 64-char hex string")
        }
        if (model.supportedTasks.isEmpty()) {
            issues += AiValidationIssue(
                "supported_tasks_empty",
                "Model should declare supported_tasks for compatibility checks",
                severity = "warning",
            )
        }

        val normalizedRuntime = model.requiredRuntime.trim().lowercase()
        if (normalizedRuntime.isNotBlank() && !backendManager.hasRuntime(normalizedRuntime)) {
            issues += AiValidationIssue(
                "runtime_unavailable",
                "Required runtime '${model.requiredRuntime}' is not registered",
                severity = "warning",
            )
        }

        model.supportedRuntimes.forEach { runtime ->
            if (runtime.isNotBlank() && !backendManager.hasRuntime(runtime)) {
                issues += AiValidationIssue(
                    "supported_runtime_unavailable",
                    "Supported runtime '$runtime' is not currently registered",
                    severity = "warning",
                )
            }
        }

        val hardwareReport = resourceManager.validateHardwareRequirements(model.requiredHardware)
        issues += hardwareReport.issues

        return AiValidationReport(
            valid = issues.none { it.severity == "error" },
            issues = issues,
            metadata = mapOf(
                "model_id" to model.modelId,
                "version" to model.version,
            ),
        )
    }

    fun validateInstalledModel(modelId: String, version: String): AiValidationReport {
        val model = repository.getModel(modelId, version)
        if (model == null) {
            return AiValidationReport(
                valid = false,
                issues = listOf(
                    AiValidationIssue("model_not_found", "Model $modelId@$version is not registered"),
                ),
            )
        }

        val issues = mutableListOf<AiValidationIssue>()
        if (!model.installed) {
            issues += AiValidationIssue("model_not_installed", "Model $modelId@$version is not marked as installed")
        }

        if (model.installPath.isBlank()) {
            issues += AiValidationIssue("install_path_missing", "Installed model is missing install_path")
        } else {
            val file = File(model.installPath)
            if (!file.exists()) {
                issues += AiValidationIssue("file_missing", "Installed model file does not exist: ${model.installPath}")
            } else {
                if (model.sizeBytes > 0 && file.length() != model.sizeBytes) {
                    issues += AiValidationIssue(
                        "size_mismatch",
                        "File size ${file.length()} does not match expected ${model.sizeBytes}",
                    )
                }
                if (model.hashSha256.isNotBlank()) {
                    val actual = sha256Hex(file)
                    if (!actual.equals(model.hashSha256, ignoreCase = true)) {
                        issues += AiValidationIssue("hash_mismatch", "Computed SHA-256 does not match registry hash")
                    }
                }
            }
        }

        model.dependencies.forEach { dependency ->
            val dependencyModelId = dependency.substringBefore('@').trim()
            if (dependencyModelId.isBlank()) {
                return@forEach
            }
            val installedDependency = repository.listModels(installedOnly = true).any { it.modelId == dependencyModelId }
            if (!installedDependency) {
                issues += AiValidationIssue(
                    "dependency_missing",
                    "Required dependency model '$dependencyModelId' is not installed",
                )
            }
        }

        val runtimeReport = validateModelDescriptor(model)
        issues += runtimeReport.issues.filter {
            it.code == "runtime_unavailable" ||
                it.code == "supported_runtime_unavailable" ||
                it.code == "simd_missing"
        }

        return AiValidationReport(
            valid = issues.none { it.severity == "error" },
            issues = issues,
            metadata = mapOf("model" to model.toMap()),
        )
    }

    fun validateExecutionRequest(request: AiExecutionRequest): AiValidationReport {
        val issues = mutableListOf<AiValidationIssue>()
        val normalizedTaskType = AiTaskTypes.normalize(request.taskType)

        if (normalizedTaskType.isBlank()) {
            issues += AiValidationIssue("task_type_missing", "task_type is required")
        } else if (!AiTaskTypes.isSupported(normalizedTaskType)) {
            issues += AiValidationIssue(
                "task_type_unsupported",
                "task_type '$normalizedTaskType' is not supported by Local AI execution layer",
            )
        }

        if (AiTaskTypes.isExecutionTask(normalizedTaskType)) {
            if (request.modelId.isBlank()) {
                issues += AiValidationIssue("task_model_missing", "Execution tasks must provide model_id")
            }
            if (request.version.isBlank()) {
                issues += AiValidationIssue("task_model_version_missing", "Execution tasks must provide version")
            }
        }

        if (request.runtimeHint.isNotBlank() && !backendManager.hasRuntime(request.runtimeHint)) {
            issues += AiValidationIssue(
                "runtime_unavailable",
                "Requested runtime '${request.runtimeHint}' is not registered",
            )
        }

        if (request.deadlineAtMs > 0 && request.deadlineAtMs <= System.currentTimeMillis()) {
            issues += AiValidationIssue("deadline_expired", "Execution deadline is already expired")
        }

        return AiValidationReport(
            valid = issues.none { it.severity == "error" },
            issues = issues,
            metadata = mapOf(
                "task_id" to request.taskId,
                "task_type" to normalizedTaskType,
            ),
        )
    }

    fun validateModelCompatibility(
        task: AiTaskRecord,
        model: AiModelDescriptor?,
        runtimeId: String,
        backendCapability: AiBackendCapability,
    ): AiValidationReport {
        val issues = mutableListOf<AiValidationIssue>()
        val normalizedTaskType = AiTaskTypes.normalize(task.taskType)

        if (AiTaskTypes.isExecutionTask(normalizedTaskType) && model == null) {
            issues += AiValidationIssue("model_not_found", "Task references a model that is not installed")
            return AiValidationReport(valid = false, issues = issues)
        }

        if (model != null) {
            if (!model.installed && AiTaskTypes.isExecutionTask(normalizedTaskType)) {
                issues += AiValidationIssue("model_not_installed", "Model ${model.modelId}@${model.version} is not installed")
            }

            if (model.supportedTasks.isNotEmpty() && normalizedTaskType !in model.supportedTasks.map { AiTaskTypes.normalize(it) }.toSet()) {
                issues += AiValidationIssue(
                    "model_task_unsupported",
                    "Model ${model.modelId}@${model.version} does not support task $normalizedTaskType",
                )
            }

            if (model.requiredRuntime.isNotBlank() && !model.requiredRuntime.equals(runtimeId, ignoreCase = true)) {
                issues += AiValidationIssue(
                    "runtime_incompatible",
                    "Model requires runtime ${model.requiredRuntime} but selected runtime is $runtimeId",
                )
            }

            if (
                model.supportedRuntimes.isNotEmpty() &&
                model.supportedRuntimes.none { it.equals(runtimeId, ignoreCase = true) }
            ) {
                issues += AiValidationIssue(
                    "runtime_not_supported_by_model",
                    "Selected runtime $runtimeId is not listed in model supported_runtimes",
                )
            }

            val hardwareReport = resourceManager.validateHardwareRequirements(model.requiredHardware)
            issues += hardwareReport.issues
        }

        if (
            backendCapability.supportedTasks.isNotEmpty() &&
            normalizedTaskType !in backendCapability.supportedTasks.map { AiTaskTypes.normalize(it) }.toSet()
        ) {
            issues += AiValidationIssue(
                "backend_task_unsupported",
                "Backend ${backendCapability.runtimeId} does not support task $normalizedTaskType",
            )
        }

        return AiValidationReport(
            valid = issues.none { it.severity == "error" },
            issues = issues,
            metadata = mapOf(
                "task_id" to task.taskId,
                "task_type" to normalizedTaskType,
                "runtime_id" to runtimeId,
                "backend" to backendCapability.toMap(),
            ),
        )
    }

    fun validateInfrastructureSnapshot(): AiValidationReport {
        val issues = mutableListOf<AiValidationIssue>()
        if (backendManager.listBackends().isEmpty()) {
            issues += AiValidationIssue(
                "backend_registry_empty",
                "No backends are registered; execution tasks cannot run until a backend is registered",
                severity = "warning",
            )
        }

        val tasks = repository.listTasks(limit = 500)
        val installedModels = repository.listModels(installedOnly = true).size

        return AiValidationReport(
            valid = issues.none { it.severity == "error" },
            issues = issues,
            metadata = mapOf(
                "queue_pending" to tasks.count { it.status == "pending" },
                "queue_running" to tasks.count { it.status == "running" },
                "queue_paused" to tasks.count { it.status == "paused" },
                "queue_failed" to tasks.count { it.status == "failed" },
                "installed_models" to installedModels,
                "registered_backends" to backendManager.listBackends().size,
            ),
        )
    }

    private fun sha256Hex(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) {
                    break
                }
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}

class DefaultLocalAiRuntimeGateway(
    private val validationService: LocalAiValidationService,
) : LocalAiRuntimeGateway {

    override suspend fun execute(
        request: AiExecutionRequest,
        backend: AiBackendRuntime,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        val validation = validationService.validateExecutionRequest(request)
        if (!validation.valid) {
            return AiExecutionResult(
                ok = false,
                status = "invalid",
                message = "Execution request is invalid",
                details = validation.toMap(),
            )
        }

        val normalizedTaskType = AiTaskTypes.normalize(request.taskType)
        if (
            backend.supportedTasks.isNotEmpty() &&
            normalizedTaskType !in backend.supportedTasks.map { AiTaskTypes.normalize(it) }.toSet()
        ) {
            return AiExecutionResult(
                ok = false,
                status = "unsupported",
                message = "Backend ${backend.runtimeId} does not support task $normalizedTaskType",
                details = mapOf(
                    "runtime_id" to backend.runtimeId,
                    "task_type" to normalizedTaskType,
                ),
            )
        }

        val timeoutWindowMs = if (request.deadlineAtMs <= 0L) {
            0L
        } else {
            request.deadlineAtMs - System.currentTimeMillis()
        }

        if (request.deadlineAtMs > 0L && timeoutWindowMs <= 0L) {
            return AiExecutionResult(
                ok = false,
                status = "timeout",
                message = "Task exceeded configured timeout before execution started",
            )
        }

        return runCatching {
            if (timeoutWindowMs > 0L) {
                withTimeoutOrNull(timeoutWindowMs) {
                    backend.execute(request, reporter)
                } ?: AiExecutionResult(
                    ok = false,
                    status = "timeout",
                    message = "Task exceeded execution timeout",
                )
            } else {
                backend.execute(request, reporter)
            }
        }.getOrElse { error ->
            if (error is CancellationException) {
                AiExecutionResult(
                    ok = false,
                    status = "cancelled",
                    message = error.message ?: "cancelled",
                )
            } else {
                AiExecutionResult(
                    ok = false,
                    status = "runtime_failure",
                    message = error.message ?: error.javaClass.simpleName,
                    details = mapOf("runtime_id" to backend.runtimeId),
                )
            }
        }
    }
}

class LocalAiExecutionQueue(
    private val repository: LocalAiRepository,
    private val settingsProvider: () -> AiSettings,
) {
    fun enqueueTask(
        taskType: String,
        modelId: String = "",
        version: String = "",
        runtimeHint: String = "",
        priority: Int = 0,
        maxRetries: Int = settingsProvider().maxQueueRetries,
        timeoutMs: Long = settingsProvider().defaultTaskTimeoutMs,
        dependencyTaskIds: List<String> = emptyList(),
        payload: Map<String, Any> = emptyMap(),
    ): AiTaskRecord {
        val now = System.currentTimeMillis()
        val normalizedTaskType = AiTaskTypes.normalize(taskType.ifBlank { "custom" })
        val task = AiTaskRecord(
            taskId = UUID.randomUUID().toString(),
            taskType = normalizedTaskType,
            modelId = modelId.trim(),
            version = version.trim(),
            runtimeHint = runtimeHint.trim(),
            priority = priority,
            status = "pending",
            progress = 0.0,
            retryCount = 0,
            maxRetries = maxRetries.coerceAtLeast(0),
            cancellationRequested = false,
            pauseRequested = false,
            dependencyTaskIds = dependencyTaskIds.map { it.trim() }.filter { it.isNotBlank() }.distinct(),
            nextRunAtMs = now,
            timeoutMs = timeoutMs.coerceAtLeast(1_000L),
            payload = payload,
            result = emptyMap(),
            createdAtMs = now,
            updatedAtMs = now,
            startedAtMs = 0L,
            finishedAtMs = 0L,
            errorMessage = "",
            sessionId = "",
        )
        repository.upsertTask(task)
        return task
    }

    fun listTasks(limit: Int = 200): List<AiTaskRecord> {
        return repository.listTasks(limit)
    }

    fun getTask(taskId: String): AiTaskRecord? {
        return repository.getTask(taskId)
    }

    fun listRunnableTasks(nowMs: Long, limit: Int): List<AiTaskRecord> {
        return repository.listRunnablePendingTasks(nowMs, limit)
    }

    fun listDependencyStatuses(task: AiTaskRecord): Map<String, String> {
        return repository.listTaskStatuses(task.dependencyTaskIds)
    }

    fun recoverInterruptedTasks(): Int {
        return repository.recoverInterruptedTasks()
    }

    fun markTaskRunning(taskId: String): Boolean {
        return repository.markTaskRunning(taskId)
    }

    fun setTaskSession(taskId: String, sessionId: String): Boolean {
        return repository.setTaskSession(taskId, sessionId)
    }

    fun updateTaskProgress(taskId: String, progress: Double, message: String): Boolean {
        return repository.updateTaskProgress(taskId, progress, message)
    }

    fun markTaskPaused(taskId: String, message: String): Boolean {
        return repository.markTaskPaused(taskId, message)
    }

    fun markTaskCompleted(taskId: String, status: String, result: Map<String, Any>, errorMessage: String = ""): Boolean {
        return repository.markTaskCompleted(taskId, status, result, errorMessage)
    }

    fun scheduleRetry(taskId: String, nextRunAtMs: Long, errorMessage: String): Boolean {
        return repository.scheduleTaskRetry(taskId, nextRunAtMs, errorMessage)
    }

    fun cancelTask(taskId: String): Boolean {
        val normalized = taskId.trim()
        if (normalized.isBlank()) {
            return false
        }
        val cancelledPending = repository.cancelPendingTask(normalized)
        if (cancelledPending) {
            return true
        }
        return repository.requestTaskCancellation(normalized)
    }

    fun pauseTask(taskId: String): Boolean {
        val normalized = taskId.trim()
        if (normalized.isBlank()) {
            return false
        }
        val pausedPending = repository.pausePendingTask(normalized)
        if (pausedPending) {
            return true
        }
        return repository.requestTaskPause(normalized)
    }

    fun resumeTask(taskId: String): Boolean {
        val normalized = taskId.trim()
        if (normalized.isBlank()) {
            return false
        }
        return repository.resumePausedTask(normalized)
    }

    fun retryTask(taskId: String): Boolean {
        val normalized = taskId.trim()
        if (normalized.isBlank()) {
            return false
        }
        return repository.retryTask(normalized)
    }
}

class LocalAiRuntimeSelector(
    private val settingsProvider: () -> AiSettings,
) {
    fun select(
        task: AiTaskRecord,
        model: AiModelDescriptor?,
        availableBackends: List<AiBackendRuntime>,
    ): List<String> {
        val candidates = linkedSetOf<String>()
        val settings = settingsProvider()

        if (task.runtimeHint.isNotBlank()) {
            candidates += task.runtimeHint.trim().lowercase()
        }
        if (model != null) {
            if (model.requiredRuntime.isNotBlank()) {
                candidates += model.requiredRuntime.trim().lowercase()
            }
            model.supportedRuntimes
                .map { it.trim().lowercase() }
                .filter { it.isNotBlank() }
                .forEach { candidates += it }
        }
        settings.preferredRuntimeOrder
            .map { it.trim().lowercase() }
            .filter { it.isNotBlank() }
            .forEach { candidates += it }

        availableBackends.forEach { backend ->
            candidates += backend.runtimeId.trim().lowercase()
            candidates += backend.runtimeType.raw.trim().lowercase()
        }

        if (model != null && model.supportedRuntimes.isNotEmpty()) {
            val allowed = model.supportedRuntimes.map { it.trim().lowercase() }.toSet()
            val filtered = candidates.filter {
                it in allowed || availableBackends.any { backend ->
                    backend.runtimeId.equals(it, ignoreCase = true) && backend.runtimeType.raw.lowercase() in allowed
                }
            }
            if (filtered.isNotEmpty()) {
                return filtered
            }
        }

        return candidates.toList()
    }
}

class LocalAiBackendSelector(
    private val backendManager: LocalAiBackendManager,
) {
    data class Selection(
        val backend: AiBackendRuntime,
        val capability: AiBackendCapability,
        val runtimeId: String,
    )

    fun select(runtimeCandidates: List<String>, taskType: String): Selection? {
        val normalizedTaskType = AiTaskTypes.normalize(taskType)
        val allBackends = backendManager.snapshotBackends()

        runtimeCandidates.forEach { candidate ->
            val runtimeMatches = backendManager.resolveByRuntime(candidate)
            runtimeMatches.forEach { backend ->
                val capability = backend.detectCapabilities()
                if (capability.supportedTasks.isEmpty() || normalizedTaskType in capability.supportedTasks.map { AiTaskTypes.normalize(it) }.toSet()) {
                    return Selection(
                        backend = backend,
                        capability = capability,
                        runtimeId = candidate,
                    )
                }
            }
        }

        allBackends.forEach { backend ->
            val capability = backend.detectCapabilities()
            if (capability.supportedTasks.isEmpty() || normalizedTaskType in capability.supportedTasks.map { AiTaskTypes.normalize(it) }.toSet()) {
                return Selection(
                    backend = backend,
                    capability = capability,
                    runtimeId = backend.runtimeId,
                )
            }
        }

        return null
    }
}

class LocalAiExecutionHistory(
    private val repository: LocalAiRepository,
) {
    fun startSession(context: AiExecutionContext): AiExecutionSessionRecord {
        val now = System.currentTimeMillis()
        val session = AiExecutionSessionRecord(
            sessionId = context.request.sessionId,
            taskId = context.task.taskId,
            taskType = context.task.taskType,
            modelId = context.task.modelId,
            version = context.task.version,
            runtimeId = context.runtimeId,
            backendId = context.backendId,
            status = "running",
            progress = 0.0,
            retryCount = context.task.retryCount,
            reservationBytes = context.reservationBytes,
            context = context.toMap(),
            result = emptyMap(),
            createdAtMs = now,
            updatedAtMs = now,
            startedAtMs = now,
            finishedAtMs = 0L,
            errorMessage = "",
        )
        repository.upsertExecutionSession(session)
        recordEvent(
            sessionId = session.sessionId,
            taskId = session.taskId,
            eventType = "session_started",
            message = "Execution session created",
            progress = 0.0,
            payload = mapOf(
                "runtime_id" to context.runtimeId,
                "backend_id" to context.backendId,
            ),
        )
        return session
    }

    fun recordEvent(
        sessionId: String,
        taskId: String,
        eventType: String,
        message: String,
        progress: Double,
        payload: Map<String, Any> = emptyMap(),
    ) {
        repository.appendExecutionEvent(
            AiExecutionEventRecord(
                eventId = 0L,
                sessionId = sessionId,
                taskId = taskId,
                eventType = eventType,
                message = message,
                progress = progress.coerceIn(0.0, 1.0),
                payload = payload,
                createdAtMs = System.currentTimeMillis(),
            ),
        )
    }

    fun updateSessionProgress(sessionId: String, progress: Double, message: String, payload: Map<String, Any>) {
        val current = repository.getExecutionSession(sessionId) ?: return
        val updated = current.copy(
            progress = progress.coerceIn(0.0, 1.0),
            updatedAtMs = System.currentTimeMillis(),
            result = current.result + mapOf(
                "last_message" to message,
                "last_payload" to payload,
            ),
        )
        repository.upsertExecutionSession(updated)
    }

    fun completeSession(
        sessionId: String,
        status: String,
        result: Map<String, Any>,
        errorMessage: String,
    ) {
        val current = repository.getExecutionSession(sessionId) ?: return
        val progress = if (status == "succeeded") 1.0 else current.progress
        val finishedAt = System.currentTimeMillis()
        repository.upsertExecutionSession(
            current.copy(
                status = status,
                progress = progress,
                result = result,
                updatedAtMs = finishedAt,
                finishedAtMs = finishedAt,
                errorMessage = errorMessage,
            ),
        )
        recordEvent(
            sessionId = sessionId,
            taskId = current.taskId,
            eventType = "session_completed",
            message = if (errorMessage.isBlank()) "Session completed" else errorMessage,
            progress = progress,
            payload = mapOf("status" to status),
        )
    }

    fun listSessions(limit: Int): List<AiExecutionSessionRecord> {
        return repository.listExecutionSessions(limit)
    }

    fun listEvents(sessionId: String, limit: Int): List<AiExecutionEventRecord> {
        return repository.listExecutionEvents(sessionId, limit)
    }
}

private class AiTaskCancelledException(message: String) : CancellationException(message)

private class AiTaskPausedException(message: String) : CancellationException(message)

class LocalAiProgressManager(
    private val queue: LocalAiExecutionQueue,
    private val history: LocalAiExecutionHistory,
) {
    fun reporter(taskId: String, sessionId: String): AiProgressReporter {
        return AiProgressReporter { progress, message ->
            val normalizedProgress = progress.coerceIn(0.0, 1.0)
            queue.updateTaskProgress(taskId, normalizedProgress, message)
            history.updateSessionProgress(
                sessionId = sessionId,
                progress = normalizedProgress,
                message = message,
                payload = mapOf("source" to "reporter"),
            )
            history.recordEvent(
                sessionId = sessionId,
                taskId = taskId,
                eventType = "progress",
                message = message,
                progress = normalizedProgress,
            )

            val task = queue.getTask(taskId) ?: return@AiProgressReporter
            if (task.cancellationRequested) {
                throw AiTaskCancelledException("Task cancelled by caller")
            }
            if (task.pauseRequested) {
                throw AiTaskPausedException("Task paused by caller")
            }
        }
    }
}

class LocalAiRetryManager(
    private val settingsProvider: () -> AiSettings,
) {
    fun decide(task: AiTaskRecord, status: String, message: String): AiRetryDecision {
        val normalizedStatus = status.trim().lowercase()
        if (task.retryCount >= task.maxRetries) {
            return AiRetryDecision(false, 0L, "max_retries_exceeded")
        }
        if (normalizedStatus in nonRetryableStatuses) {
            return AiRetryDecision(false, 0L, "non_retryable_status")
        }
        if (message.contains("unsupported", ignoreCase = true)) {
            return AiRetryDecision(false, 0L, "unsupported_capability")
        }

        val baseDelayMs = settingsProvider().schedulerPollIntervalMs.coerceAtLeast(250L) * 4L
        val exponent = task.retryCount.coerceAtMost(8)
        var backoffMs = baseDelayMs
        repeat(exponent) {
            backoffMs = (backoffMs * 2L).coerceAtMost(60_000L)
        }
        val nextRunAtMs = System.currentTimeMillis() + backoffMs
        return AiRetryDecision(true, nextRunAtMs, "retry_backoff_${backoffMs}ms")
    }

    private val nonRetryableStatuses = setOf(
        "cancelled",
        "paused",
        "invalid",
        "unsupported",
        "incompatible_model_version",
        "missing_outputs",
        "corrupted_outputs",
    )
}

class LocalAiResultValidator {
    fun validate(context: AiExecutionContext, result: AiExecutionResult): AiValidationReport {
        val issues = mutableListOf<AiValidationIssue>()

        if (!result.ok) {
            val normalizedStatus = result.status.trim().lowercase()
            when {
                normalizedStatus.contains("timeout") -> {
                    issues += AiValidationIssue("timeout", "Execution timed out")
                }

                normalizedStatus.contains("resource") || result.message.contains("out of memory", ignoreCase = true) -> {
                    issues += AiValidationIssue("resource_exhaustion", "Execution failed due to resource exhaustion")
                }

                normalizedStatus.contains("unsupported") -> {
                    issues += AiValidationIssue("unsupported_capabilities", "Execution failed due to unsupported capabilities")
                }

                normalizedStatus.contains("runtime") -> {
                    issues += AiValidationIssue("runtime_failures", result.message.ifBlank { "Runtime failure" })
                }

                else -> {
                    issues += AiValidationIssue("backend_failures", result.message.ifBlank { "Backend execution failed" })
                }
            }
            return AiValidationReport(valid = false, issues = issues)
        }

        if (result.details.isEmpty()) {
            issues += AiValidationIssue("missing_outputs", "Execution completed without result details")
            return AiValidationReport(valid = false, issues = issues)
        }

        val modelVersionFromResult = result.details["model_version"]?.toString().orEmpty()
        if (
            context.request.version.isNotBlank() &&
            modelVersionFromResult.isNotBlank() &&
            !modelVersionFromResult.equals(context.request.version, ignoreCase = true)
        ) {
            issues += AiValidationIssue(
                "incompatible_model_version",
                "Result model_version '$modelVersionFromResult' does not match requested version '${context.request.version}'",
            )
        }

        val outputs = (result.details["outputs"] as? List<*>)?.mapNotNull { it as? Map<*, *> } ?: emptyList()
        val hasDirectResult = result.details.containsKey("result") || result.details.containsKey("output")
        if (outputs.isEmpty() && !hasDirectResult) {
            issues += AiValidationIssue("missing_outputs", "Execution result has no outputs")
        }

        outputs.forEachIndexed { index, rawOutput ->
            val output = rawOutput.entries
                .filter { it.key != null }
                .associate { it.key.toString() to (it.value ?: "") }

            val outputPath = output["path"]?.toString()?.trim().orEmpty()
            if (outputPath.isBlank()) {
                issues += AiValidationIssue("invalid_outputs", "Output at index $index is missing path")
                return@forEachIndexed
            }

            val file = File(outputPath)
            if (!file.exists()) {
                issues += AiValidationIssue("missing_outputs", "Output file does not exist: $outputPath")
                return@forEachIndexed
            }

            val expectedSize = output["size_bytes"]?.toString()?.toLongOrNull()
            if (expectedSize != null && expectedSize > 0 && expectedSize != file.length()) {
                issues += AiValidationIssue("corrupted_outputs", "Output file size mismatch for $outputPath")
            }

            val expectedHash = output["sha256"]?.toString()?.trim().orEmpty().lowercase()
            if (expectedHash.isNotBlank()) {
                val actualHash = sha256Hex(file)
                if (!expectedHash.equals(actualHash, ignoreCase = true)) {
                    issues += AiValidationIssue("corrupted_outputs", "Output file hash mismatch for $outputPath")
                }
            }
        }

        validateTaskSpecificDetails(
            taskType = AiTaskTypes.normalize(context.task.taskType),
            details = result.details,
            issues = issues,
        )

        return AiValidationReport(
            valid = issues.none { it.severity == "error" },
            issues = issues,
            metadata = mapOf(
                "task_id" to context.task.taskId,
                "session_id" to context.request.sessionId,
            ),
        )
    }

    private fun validateTaskSpecificDetails(
        taskType: String,
        details: Map<String, Any>,
        issues: MutableList<AiValidationIssue>,
    ) {
        val result = details["result"].asStringAnyMap()
        when (taskType) {
            "embedding_generation" -> {
                val embedding = (details["embedding"] as? List<*>)?.mapNotNull { it as? Number } ?: emptyList()
                if (embedding.isEmpty()) {
                    issues += AiValidationIssue("missing_outputs", "Embedding generation result is missing embedding vector")
                }
            }

            "similarity_search" -> {
                val hasMatches = details.containsKey("matches") || result.containsKey("matches")
                if (!hasMatches) {
                    issues += AiValidationIssue("missing_outputs", "Similarity search result is missing matches")
                }
            }

            "ocr" -> {
                val text = result["text"]?.toString().orEmpty().ifBlank { details["text"]?.toString().orEmpty() }
                if (text.isBlank()) {
                    issues += AiValidationIssue("missing_outputs", "OCR result is missing extracted text")
                }
            }

            "captioning" -> {
                val caption = result["caption"]?.toString().orEmpty().ifBlank { details["caption"]?.toString().orEmpty() }
                if (caption.isBlank()) {
                    issues += AiValidationIssue("missing_outputs", "Captioning result is missing caption text")
                }
            }

            "character_recognition",
            "series_recognition",
            "artist_recognition" -> {
                val topMatch = result["top_match"]?.toString().orEmpty()
                val candidates = result["candidates"].asListOfMaps()
                if (topMatch.isBlank() && candidates.isEmpty()) {
                    issues += AiValidationIssue("missing_outputs", "$taskType result has no top_match or candidates")
                }
            }

            "tag_prediction" -> {
                val tags = result["tags"].asStringList()
                if (tags.isEmpty()) {
                    issues += AiValidationIssue("missing_outputs", "Tag prediction result is missing predicted tags")
                }
            }

            "metadata_extraction" -> {
                val metadata = result["metadata"].asStringAnyMap()
                if (metadata.isEmpty()) {
                    issues += AiValidationIssue("missing_outputs", "Metadata extraction result is missing metadata payload")
                }
            }

            "prompt_generation" -> {
                val prompt = result["prompt"]?.toString().orEmpty()
                if (prompt.isBlank()) {
                    issues += AiValidationIssue("missing_outputs", "Prompt generation result is missing prompt text")
                }
            }

            "duplicate_detection" -> {
                if (!result.containsKey("groups")) {
                    issues += AiValidationIssue("missing_outputs", "Duplicate detection result is missing duplicate groups")
                }
            }

            "classification" -> {
                val label = result["label"]?.toString().orEmpty()
                val ranked = result["ranked_labels"].asListOfMaps()
                if (label.isBlank() && ranked.isEmpty()) {
                    issues += AiValidationIssue("missing_outputs", "Classification result is missing labels")
                }
            }

            "detection" -> {
                if (!result.containsKey("detections")) {
                    issues += AiValidationIssue("missing_outputs", "Detection result is missing detection list")
                }
            }

            "face_feature_extraction" -> {
                val features = result["feature_vector"] as? List<*>
                if (features.isNullOrEmpty()) {
                    issues += AiValidationIssue("missing_outputs", "Face feature extraction result is missing feature vector")
                }
            }

            "knowledge_pack_execution" -> {
                val packId = result["knowledge_pack_id"]?.toString().orEmpty()
                val operations = result["operations"].asListOfMaps()
                if (packId.isBlank() || operations.isEmpty()) {
                    issues += AiValidationIssue(
                        "missing_outputs",
                        "Knowledge pack execution result is missing pack identifier or operations",
                    )
                }
            }
        }
    }

    private fun Any?.asStringAnyMap(): Map<String, Any> {
        val source = this as? Map<*, *> ?: return emptyMap()
        val result = linkedMapOf<String, Any>()
        source.forEach { (keyRaw, value) ->
            val key = keyRaw?.toString()?.trim().orEmpty()
            if (key.isBlank() || value == null) {
                return@forEach
            }
            result[key] = value
        }
        return result
    }

    private fun Any?.asListOfMaps(): List<Map<String, Any>> {
        val values = this as? List<*> ?: return emptyList()
        return values.mapNotNull { item ->
            val map = item as? Map<*, *> ?: return@mapNotNull null
            val normalized = linkedMapOf<String, Any>()
            map.forEach { (keyRaw, value) ->
                val key = keyRaw?.toString()?.trim().orEmpty()
                if (key.isBlank() || value == null) {
                    return@forEach
                }
                normalized[key] = value
            }
            normalized
        }
    }

    private fun Any?.asStringList(): List<String> {
        return when (this) {
            is List<*> -> this.mapNotNull { it?.toString()?.trim() }.filter { it.isNotBlank() }
            is String -> this
                .split(',', '|')
                .map { it.trim() }
                .filter { it.isNotBlank() }

            else -> emptyList()
        }
    }

    private fun sha256Hex(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) {
                    break
                }
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}

class LocalAiExecutionCache(
    context: Context,
    private val modelCache: LocalAiModelCache,
) {
    private val cacheRoot = File(context.filesDir, "local_ai_execution_cache").apply { mkdirs() }

    fun lookup(context: AiExecutionContext): AiExecutionResult? {
        val key = resultCacheKey(context)
        val entry = modelCache.getEntry(key) ?: return null
        val metadataFile = File(entry.artifactPath)
        if (!metadataFile.exists()) {
            modelCache.removeEntry(key)
            return null
        }

        val payload = runCatching {
            LocalAiJson.decodeMap(metadataFile.readText())
        }.getOrElse {
            modelCache.removeEntry(key)
            return null
        }
        modelCache.touch(key)

        val details = payload["details"].toStringMap()
        return AiExecutionResult(
            ok = payload["ok"].toBooleanValue(defaultValue = false),
            status = payload["status"]?.toString().orEmpty(),
            message = payload["message"]?.toString().orEmpty(),
            details = details + mapOf("cache_hit" to true),
        )
    }

    fun store(context: AiExecutionContext, result: AiExecutionResult): Map<String, Any> {
        val key = resultCacheKey(context)
        val now = System.currentTimeMillis()
        val metadataFile = File(cacheRoot, "$key.json")
        val payload = linkedMapOf<String, Any>(
            "ok" to result.ok,
            "status" to result.status,
            "message" to result.message,
            "details" to result.details,
            "cached_at_ms" to now,
        )
        metadataFile.writeText(LocalAiJson.encodeMap(payload))

        modelCache.upsertEntry(
            modelId = context.task.modelId.ifBlank { "_global" },
            cacheKey = key,
            artifactPath = metadataFile.absolutePath,
            sizeBytes = metadataFile.length(),
            pinned = false,
            metadata = mapOf(
                "cache_type" to "execution_result",
                "task_type" to context.task.taskType,
                "session_id" to context.request.sessionId,
            ),
        )

        cacheEmbeddingArtifacts(context, result)
        cacheTensorArtifacts(context, result)
        cacheExecutionMetadata(context, metadataFile)
        cacheTaskArtifacts(context, result)

        return mapOf(
            "cache_key" to key,
            "artifact_path" to metadataFile.absolutePath,
            "size_bytes" to metadataFile.length(),
        )
    }

    private fun cacheEmbeddingArtifacts(context: AiExecutionContext, result: AiExecutionResult) {
        val embeddingVector = result.details["embedding"] as? List<*>
        if (embeddingVector == null || embeddingVector.isEmpty()) {
            return
        }
        val file = File(cacheRoot, "embedding_${context.request.sessionId}.json")
        file.writeText(LocalAiJson.encodeMap(mapOf("embedding" to embeddingVector)))
        modelCache.upsertEntry(
            modelId = context.task.modelId.ifBlank { "_global" },
            cacheKey = "embedding:${context.task.taskId}",
            artifactPath = file.absolutePath,
            sizeBytes = file.length(),
            metadata = mapOf(
                "cache_type" to "embeddings",
                "task_type" to context.task.taskType,
            ),
        )
    }

    private fun cacheTensorArtifacts(context: AiExecutionContext, result: AiExecutionResult) {
        val tensors = (result.details["intermediate_tensors"] as? List<*>)?.mapNotNull { it?.toString() } ?: emptyList()
        tensors.forEachIndexed { index, tensorPath ->
            val file = File(tensorPath)
            if (!file.exists()) {
                return@forEachIndexed
            }
            modelCache.upsertEntry(
                modelId = context.task.modelId.ifBlank { "_global" },
                cacheKey = "tensor:${context.task.taskId}:$index",
                artifactPath = file.absolutePath,
                sizeBytes = file.length(),
                metadata = mapOf(
                    "cache_type" to "intermediate_tensors",
                    "task_type" to context.task.taskType,
                ),
            )
        }
    }

    private fun cacheExecutionMetadata(context: AiExecutionContext, metadataFile: File) {
        modelCache.upsertEntry(
            modelId = context.task.modelId.ifBlank { "_global" },
            cacheKey = "execution_metadata:${context.request.sessionId}",
            artifactPath = metadataFile.absolutePath,
            sizeBytes = metadataFile.length(),
            metadata = mapOf(
                "cache_type" to "execution_metadata",
                "session_id" to context.request.sessionId,
                "runtime_id" to context.runtimeId,
            ),
        )
    }

    private fun cacheTaskArtifacts(context: AiExecutionContext, result: AiExecutionResult) {
        val normalizedTaskType = AiTaskTypes.normalize(context.task.taskType)
        val supported = setOf(
            "ocr",
            "captioning",
            "character_recognition",
            "series_recognition",
            "artist_recognition",
            "tag_prediction",
            "metadata_extraction",
            "prompt_generation",
            "duplicate_detection",
            "classification",
            "detection",
            "face_feature_extraction",
            "knowledge_pack_execution",
        )
        if (normalizedTaskType !in supported) {
            return
        }

        val artifactPayload = linkedMapOf<String, Any>(
            "task_id" to context.task.taskId,
            "task_type" to normalizedTaskType,
            "session_id" to context.request.sessionId,
            "model_id" to context.task.modelId,
            "model_version" to context.task.version,
            "runtime_id" to context.runtimeId,
            "payload" to context.task.payload,
            "result" to result.details,
            "cached_at_ms" to System.currentTimeMillis(),
        )
        val file = File(cacheRoot, "task_${normalizedTaskType}_${context.request.sessionId}.json")
        file.writeText(LocalAiJson.encodeMap(artifactPayload))

        val cacheType = when (normalizedTaskType) {
            "ocr" -> "ocr_results"
            "captioning" -> "caption_results"
            "character_recognition", "series_recognition", "artist_recognition" -> "recognition_results"
            "tag_prediction" -> "tag_results"
            "metadata_extraction" -> "metadata_results"
            "prompt_generation" -> "prompt_results"
            "duplicate_detection" -> "duplicate_results"
            "classification" -> "classification_results"
            "detection" -> "detection_results"
            "face_feature_extraction" -> "face_feature_results"
            "knowledge_pack_execution" -> "knowledge_pack_results"
            else -> "pipeline_results"
        }

        modelCache.upsertEntry(
            modelId = context.task.modelId.ifBlank { "_global" },
            cacheKey = "task_output:${normalizedTaskType}:${context.task.taskId}",
            artifactPath = file.absolutePath,
            sizeBytes = file.length(),
            pinned = false,
            metadata = mapOf(
                "cache_type" to cacheType,
                "task_type" to normalizedTaskType,
                "session_id" to context.request.sessionId,
            ),
        )

        val imageId = context.task.payload["image_id"].toIntOrNullValue()
        if (imageId != null) {
            modelCache.upsertEntry(
                modelId = context.task.modelId.ifBlank { "_global" },
                cacheKey = "task_output_latest:${normalizedTaskType}:image:$imageId",
                artifactPath = file.absolutePath,
                sizeBytes = file.length(),
                pinned = false,
                metadata = mapOf(
                    "cache_type" to "${cacheType}_latest",
                    "task_type" to normalizedTaskType,
                    "image_id" to imageId,
                ),
            )
        }
    }

    private fun resultCacheKey(context: AiExecutionContext): String {
        val canonicalPayload = LocalAiJson.encodeMap(
            mapOf(
                "task_type" to context.task.taskType,
                "model_id" to context.task.modelId,
                "version" to context.task.version,
                "runtime_id" to context.runtimeId,
                "payload" to context.task.payload,
            ),
        )
        val digest = MessageDigest.getInstance("SHA-256")
        digest.update(canonicalPayload.toByteArray(Charsets.UTF_8))
        val hash = digest.digest().joinToString("") { "%02x".format(it) }
        return "execution_result:$hash"
    }

    private fun Any?.toStringMap(): Map<String, Any> {
        return when (this) {
            is Map<*, *> -> this.entries
                .filter { it.key != null }
                .associate { it.key.toString() to (it.value ?: "") }
            else -> emptyMap()
        }
    }

    private fun Any?.toBooleanValue(defaultValue: Boolean): Boolean {
        return when (this) {
            is Boolean -> this
            is Number -> this.toInt() != 0
            else -> this?.toString()?.equals("true", ignoreCase = true) ?: defaultValue
        }
    }

    private fun Any?.toIntOrNullValue(): Int? {
        return when (this) {
            is Number -> this.toInt()
            else -> this?.toString()?.toIntOrNull()
        }
    }
}

class LocalAiSessionCache(
    private val modelCache: LocalAiModelCache,
) {
    fun markModelLoaded(model: AiModelDescriptor, runtimeId: String, refCount: Int) {
        val cacheKey = "loaded_model:${model.modelId}:${model.version}:${runtimeId.lowercase()}"
        modelCache.upsertEntry(
            modelId = model.modelId,
            cacheKey = cacheKey,
            artifactPath = model.installPath.ifBlank { "memory://model/${model.modelId}/${model.version}" },
            sizeBytes = model.sizeBytes.coerceAtLeast(0L),
            pinned = refCount > 0,
            metadata = mapOf(
                "cache_type" to "loaded_models",
                "runtime_id" to runtimeId,
                "ref_count" to refCount,
            ),
        )
    }

    fun clearModelLoaded(model: AiModelDescriptor, runtimeId: String) {
        val cacheKey = "loaded_model:${model.modelId}:${model.version}:${runtimeId.lowercase()}"
        modelCache.removeEntry(cacheKey)
    }

    fun markCompiledSession(sessionId: String, modelId: String, runtimeId: String, backendId: String) {
        val cacheKey = "compiled_session:$sessionId"
        modelCache.upsertEntry(
            modelId = modelId.ifBlank { "_global" },
            cacheKey = cacheKey,
            artifactPath = "memory://session/$sessionId",
            sizeBytes = 0L,
            pinned = false,
            metadata = mapOf(
                "cache_type" to "compiled_sessions",
                "runtime_id" to runtimeId,
                "backend_id" to backendId,
            ),
        )
    }

    fun clearCompiledSession(sessionId: String) {
        modelCache.removeEntry("compiled_session:$sessionId")
    }
}

class LocalAiMemoryManager(
    private val hardwareProvider: () -> AiHardwareProfile,
    private val settingsProvider: () -> AiSettings,
) {
    private val reservationMutex = Mutex()
    private val reservations = linkedMapOf<String, Long>()

    suspend fun reserve(sessionId: String, requestedBytes: Long): Long? {
        return reservationMutex.withLock {
            val normalizedRequested = requestedBytes.coerceAtLeast(1L)
            val budgetBytes = computeReservationBudgetBytes()
            val usedBytes = reservations.values.sum()
            val availableBytes = (budgetBytes - usedBytes).coerceAtLeast(0L)
            if (normalizedRequested > availableBytes) {
                return@withLock null
            }
            reservations[sessionId] = normalizedRequested
            normalizedRequested
        }
    }

    suspend fun release(sessionId: String) {
        reservationMutex.withLock {
            reservations.remove(sessionId)
        }
    }

    suspend fun snapshot(): Map<String, Any> {
        return reservationMutex.withLock {
            val budgetBytes = computeReservationBudgetBytes()
            val usedBytes = reservations.values.sum()
            mapOf(
                "budget_bytes" to budgetBytes,
                "used_bytes" to usedBytes,
                "available_bytes" to (budgetBytes - usedBytes).coerceAtLeast(0L),
                "active_reservations" to reservations.size,
            )
        }
    }

    private fun computeReservationBudgetBytes(): Long {
        val profile = hardwareProvider()
        val configured = settingsProvider().maxReservedRamBytes
        val fallback = (profile.availableRamBytes * 0.60).toLong().coerceAtLeast(64L * 1024L * 1024L)
        return if (configured > 0L) {
            configured.coerceAtMost(profile.availableRamBytes)
        } else {
            fallback
        }
    }
}

class LocalAiModelLifetimeManager(
    private val sessionCache: LocalAiSessionCache,
) {
    private val lifetimeMutex = Mutex()
    private val refCounts = linkedMapOf<String, Int>()

    suspend fun acquire(model: AiModelDescriptor?, runtimeId: String): Int {
        if (model == null) {
            return 0
        }
        return lifetimeMutex.withLock {
            val key = keyOf(model, runtimeId)
            val refCount = (refCounts[key] ?: 0) + 1
            refCounts[key] = refCount
            sessionCache.markModelLoaded(model, runtimeId, refCount)
            refCount
        }
    }

    suspend fun release(model: AiModelDescriptor?, runtimeId: String): Int {
        if (model == null) {
            return 0
        }
        return lifetimeMutex.withLock {
            val key = keyOf(model, runtimeId)
            val current = (refCounts[key] ?: 0).coerceAtLeast(0)
            val next = (current - 1).coerceAtLeast(0)
            if (next <= 0) {
                refCounts.remove(key)
                sessionCache.clearModelLoaded(model, runtimeId)
            } else {
                refCounts[key] = next
                sessionCache.markModelLoaded(model, runtimeId, next)
            }
            next
        }
    }

    private fun keyOf(model: AiModelDescriptor, runtimeId: String): String {
        return "${model.modelId}:${model.version}:${runtimeId.lowercase()}"
    }
}

class LocalAiRuntimeHealthMonitor(
    private val repository: LocalAiRepository,
) {
    suspend fun capture(backend: AiBackendRuntime, phase: String): AiRuntimeHealthSnapshot {
        val startedAtMs = System.currentTimeMillis()
        val backendHealth = runCatching { backend.healthCheck() }.getOrElse { error ->
            AiBackendHealth(
                healthy = false,
                status = "error",
                latencyMs = 0L,
                metadata = mapOf("error" to (error.message ?: error.javaClass.simpleName)),
            )
        }

        val capturedAtMs = System.currentTimeMillis()
        val snapshot = AiRuntimeHealthSnapshot(
            snapshotId = 0L,
            runtimeId = backend.runtimeType.raw,
            backendId = backend.runtimeId,
            status = "$phase:${backendHealth.status}",
            healthy = backendHealth.healthy,
            latencyMs = (capturedAtMs - startedAtMs).coerceAtLeast(backendHealth.latencyMs),
            metadata = backendHealth.metadata + mapOf(
                "phase" to phase,
                "capability" to backend.detectCapabilities().toMap(),
            ),
            capturedAtMs = capturedAtMs,
        )
        repository.saveRuntimeHealthSnapshot(snapshot)
        return snapshot
    }

    fun listSnapshots(limit: Int = 200): List<AiRuntimeHealthSnapshot> {
        return repository.listRuntimeHealthSnapshots(limit)
    }
}

class LocalAiTaskDispatcher(
    private val queue: LocalAiExecutionQueue,
    private val repository: LocalAiRepository,
    private val backendManager: LocalAiBackendManager,
    private val runtimeSelector: LocalAiRuntimeSelector,
    private val backendSelector: LocalAiBackendSelector,
    private val runtimeGateway: LocalAiRuntimeGateway,
    private val validationService: LocalAiValidationService,
    private val resultValidator: LocalAiResultValidator,
    private val progressManager: LocalAiProgressManager,
    private val retryManager: LocalAiRetryManager,
    private val executionHistory: LocalAiExecutionHistory,
    private val executionCache: LocalAiExecutionCache,
    private val sessionCache: LocalAiSessionCache,
    private val memoryManager: LocalAiMemoryManager,
    private val modelLifetimeManager: LocalAiModelLifetimeManager,
    private val runtimeHealthMonitor: LocalAiRuntimeHealthMonitor,
    private val settingsProvider: () -> AiSettings,
) {
    suspend fun dispatch(task: AiTaskRecord) {
        val currentTask = queue.getTask(task.taskId) ?: return
        if (currentTask.status != "pending") {
            return
        }
        if (!queue.markTaskRunning(currentTask.taskId)) {
            return
        }

        val runningTask = queue.getTask(currentTask.taskId) ?: return
        val model = resolveTaskModel(runningTask)
        val availableBackends = backendManager.snapshotBackends()
        val runtimeCandidates = runtimeSelector.select(runningTask, model, availableBackends)
        val backendSelection = backendSelector.select(runtimeCandidates, runningTask.taskType)

        val sessionId = UUID.randomUUID().toString()
        queue.setTaskSession(runningTask.taskId, sessionId)

        var activeBackend: AiBackendRuntime? = backendSelection?.backend
        var memoryReservationBytes = 0L
        var context: AiExecutionContext? = null
        var keepCompiledSessionCache = false

        try {
            if (AiTaskTypes.isExecutionTask(runningTask.taskType) && backendSelection == null) {
                handleFailure(
                    task = runningTask,
                    sessionId = sessionId,
                    status = "unsupported",
                    message = "No compatible backend is registered for task ${runningTask.taskType}",
                    details = mapOf("runtime_candidates" to runtimeCandidates),
                )
                return
            }

            if (!AiTaskTypes.isInfrastructureTask(runningTask.taskType) && backendSelection == null) {
                handleFailure(
                    task = runningTask,
                    sessionId = sessionId,
                    status = "unsupported",
                    message = "No backend resolved for task ${runningTask.taskType}",
                    details = mapOf("runtime_candidates" to runtimeCandidates),
                )
                return
            }

            if (AiTaskTypes.isInfrastructureTask(runningTask.taskType)) {
                val pseudoContext = AiExecutionContext(
                    request = AiExecutionRequest(
                        sessionId = sessionId,
                        taskId = runningTask.taskId,
                        taskType = runningTask.taskType,
                        modelId = runningTask.modelId,
                        version = runningTask.version,
                        runtimeHint = runningTask.runtimeHint,
                        attempt = runningTask.retryCount,
                        deadlineAtMs = System.currentTimeMillis() + runningTask.timeoutMs,
                        payload = runningTask.payload,
                    ),
                    task = runningTask,
                    model = model,
                    runtimeId = "infrastructure",
                    runtimeType = AiRuntimeType.CUSTOM,
                    backendId = "local_ai_manager",
                    reservationBytes = 0L,
                    startedAtMs = System.currentTimeMillis(),
                    metadata = mapOf("mode" to "infrastructure"),
                )
                executionHistory.startSession(pseudoContext)
                executionHistory.recordEvent(
                    sessionId = sessionId,
                    taskId = runningTask.taskId,
                    eventType = "infrastructure_task",
                    message = "Infrastructure task executed by manager",
                    progress = 1.0,
                )
                val result = AiExecutionResult(
                    ok = true,
                    status = "completed",
                    message = "Infrastructure task completed",
                    details = mapOf("task_type" to runningTask.taskType),
                )
                queue.markTaskCompleted(
                    taskId = runningTask.taskId,
                    status = "succeeded",
                    result = result.details + mapOf(
                        "status" to result.status,
                        "message" to result.message,
                        "session_id" to sessionId,
                    ),
                )
                executionHistory.completeSession(
                    sessionId = sessionId,
                    status = "succeeded",
                    result = result.details,
                    errorMessage = "",
                )
                return
            }

            val runtimeId = backendSelection?.runtimeId ?: ""
            val backendCapability = backendSelection?.capability ?: AiBackendCapability(
                runtimeId = "",
                runtimeType = AiRuntimeType.CUSTOM,
                supportedTasks = emptySet(),
                supportsCancellation = false,
                supportsPauseResume = false,
                maxConcurrentTasks = 1,
            )

            val compatibilityReport = validationService.validateModelCompatibility(
                task = runningTask,
                model = model,
                runtimeId = runtimeId,
                backendCapability = backendCapability,
            )
            if (!compatibilityReport.valid) {
                handleFailure(
                    task = runningTask,
                    sessionId = sessionId,
                    status = "invalid",
                    message = "Model/runtime compatibility validation failed",
                    details = mapOf("validation" to compatibilityReport.toMap()),
                )
                return
            }

            val reservationRequestBytes = estimateReservationBytes(runningTask, model)
            val reservation = memoryManager.reserve(sessionId, reservationRequestBytes)
            if (reservation == null) {
                handleFailure(
                    task = runningTask,
                    sessionId = sessionId,
                    status = "resource_exhaustion",
                    message = "Insufficient memory reservation budget for execution",
                    details = mapOf("requested_bytes" to reservationRequestBytes),
                )
                return
            }
            memoryReservationBytes = reservation

            val timeoutMs = if (runningTask.timeoutMs > 0L) {
                runningTask.timeoutMs
            } else {
                settingsProvider().defaultTaskTimeoutMs
            }
            val executionRequest = AiExecutionRequest(
                sessionId = sessionId,
                taskId = runningTask.taskId,
                taskType = runningTask.taskType,
                modelId = runningTask.modelId,
                version = runningTask.version,
                runtimeHint = runningTask.runtimeHint,
                attempt = runningTask.retryCount,
                deadlineAtMs = System.currentTimeMillis() + timeoutMs,
                payload = runningTask.payload,
            )
            context = AiExecutionContext(
                request = executionRequest,
                task = runningTask,
                model = model,
                runtimeId = runtimeId,
                runtimeType = backendSelection?.backend?.runtimeType ?: AiRuntimeType.CUSTOM,
                backendId = backendSelection?.backend?.runtimeId ?: "",
                reservationBytes = memoryReservationBytes,
                startedAtMs = System.currentTimeMillis(),
                metadata = mapOf(
                    "runtime_candidates" to runtimeCandidates,
                    "backend_capability" to backendCapability.toMap(),
                ),
            )

            executionHistory.startSession(context)
            runtimeHealthMonitor.capture(backendSelection!!.backend, phase = "before_execute")
            modelLifetimeManager.acquire(model, runtimeId)

            val cachedResult = executionCache.lookup(context)
            if (cachedResult != null) {
                queue.markTaskCompleted(
                    taskId = runningTask.taskId,
                    status = "succeeded",
                    result = cachedResult.details + mapOf(
                        "status" to cachedResult.status,
                        "message" to cachedResult.message,
                        "session_id" to sessionId,
                        "cache_hit" to true,
                    ),
                )
                executionHistory.recordEvent(
                    sessionId = sessionId,
                    taskId = runningTask.taskId,
                    eventType = "cache_hit",
                    message = "Execution served from result cache",
                    progress = 1.0,
                )
                executionHistory.completeSession(
                    sessionId = sessionId,
                    status = "succeeded",
                    result = cachedResult.details,
                    errorMessage = "",
                )
                sessionCache.markCompiledSession(sessionId, runningTask.modelId, runtimeId, backendSelection.backend.runtimeId)
                keepCompiledSessionCache = true
                runtimeHealthMonitor.capture(backendSelection.backend, phase = "after_execute")
                return
            }

            val progressReporter = progressManager.reporter(runningTask.taskId, sessionId)
            val runtimeResult = runtimeGateway.execute(
                request = executionRequest,
                backend = backendSelection.backend,
                reporter = progressReporter,
            )
            runtimeHealthMonitor.capture(backendSelection.backend, phase = "after_execute")

            val resultValidation = resultValidator.validate(context, runtimeResult)
            if (!resultValidation.valid) {
                val validationMessage = resultValidation.issues.joinToString("; ") { it.message }
                handleFailure(
                    task = runningTask,
                    sessionId = sessionId,
                    status = if (runtimeResult.ok) "invalid_output" else runtimeResult.status,
                    message = validationMessage.ifBlank { runtimeResult.message },
                    details = mapOf(
                        "runtime_result" to runtimeResult.details,
                        "validation" to resultValidation.toMap(),
                    ),
                )
                return
            }

            val cacheReceipt = executionCache.store(context, runtimeResult)
            sessionCache.markCompiledSession(sessionId, runningTask.modelId, runtimeId, backendSelection.backend.runtimeId)
            keepCompiledSessionCache = true
            queue.markTaskCompleted(
                taskId = runningTask.taskId,
                status = "succeeded",
                result = runtimeResult.details + mapOf(
                    "status" to runtimeResult.status,
                    "message" to runtimeResult.message,
                    "session_id" to sessionId,
                    "cache" to cacheReceipt,
                ),
            )
            executionHistory.completeSession(
                sessionId = sessionId,
                status = "succeeded",
                result = runtimeResult.details + mapOf("cache" to cacheReceipt),
                errorMessage = "",
            )
        } catch (paused: AiTaskPausedException) {
            activeBackend?.requestPause(sessionId)
            queue.markTaskPaused(runningTask.taskId, paused.message ?: "paused")
            executionHistory.completeSession(
                sessionId = sessionId,
                status = "paused",
                result = mapOf("paused" to true),
                errorMessage = paused.message ?: "paused",
            )
        } catch (cancelled: AiTaskCancelledException) {
            activeBackend?.requestCancellation(sessionId)
            queue.markTaskCompleted(
                taskId = runningTask.taskId,
                status = "cancelled",
                result = mapOf(
                    "status" to "cancelled",
                    "message" to (cancelled.message ?: "cancelled"),
                    "session_id" to sessionId,
                ),
                errorMessage = cancelled.message ?: "cancelled",
            )
            executionHistory.completeSession(
                sessionId = sessionId,
                status = "cancelled",
                result = mapOf("cancelled" to true),
                errorMessage = cancelled.message ?: "cancelled",
            )
        } catch (error: Throwable) {
            handleFailure(
                task = runningTask,
                sessionId = sessionId,
                status = "runtime_failure",
                message = error.message ?: error.javaClass.simpleName,
                details = mapOf("exception" to error.javaClass.simpleName),
            )
        } finally {
            val runtimeId = context?.runtimeId.orEmpty()
            modelLifetimeManager.release(model, runtimeId)
            memoryManager.release(sessionId)
            if (!keepCompiledSessionCache) {
                sessionCache.clearCompiledSession(sessionId)
            }
        }
    }

    private suspend fun handleFailure(
        task: AiTaskRecord,
        sessionId: String,
        status: String,
        message: String,
        details: Map<String, Any>,
    ) {
        val retryDecision = retryManager.decide(task, status = status, message = message)
        val resultPayload = details + mapOf(
            "status" to status,
            "message" to message,
            "session_id" to sessionId,
        )

        if (retryDecision.shouldRetry) {
            queue.scheduleRetry(task.taskId, retryDecision.nextRunAtMs, message)
            queue.updateTaskProgress(task.taskId, 0.0, "Retry scheduled: ${retryDecision.reason}")
            executionHistory.completeSession(
                sessionId = sessionId,
                status = "retry_scheduled",
                result = resultPayload + mapOf("retry" to retryDecision.reason),
                errorMessage = message,
            )
            return
        }

        val finalStatus = if (status == "invalid_output") "failed" else status
        queue.markTaskCompleted(
            taskId = task.taskId,
            status = if (finalStatus == "runtime_failure") "failed" else finalStatus,
            result = resultPayload,
            errorMessage = message,
        )
        executionHistory.completeSession(
            sessionId = sessionId,
            status = if (finalStatus == "runtime_failure") "failed" else finalStatus,
            result = resultPayload,
            errorMessage = message,
        )
    }

    private fun resolveTaskModel(task: AiTaskRecord): AiModelDescriptor? {
        if (task.modelId.isBlank()) {
            return null
        }
        return if (task.version.isBlank()) {
            repository.getModel(task.modelId)
        } else {
            repository.getModel(task.modelId, task.version)
        }
    }

    private fun estimateReservationBytes(task: AiTaskRecord, model: AiModelDescriptor?): Long {
        val explicitReservation = (task.payload["reserve_ram_bytes"] as? Number)?.toLong()
        if (explicitReservation != null && explicitReservation > 0L) {
            return explicitReservation
        }
        val modelSize = model?.sizeBytes ?: 8L * 1024L * 1024L
        val multiplier = when (AiTaskTypes.normalize(task.taskType)) {
            "embedding_generation", "similarity_search", "duplicate_detection", "face_feature_extraction" -> 3L
            "ocr", "captioning", "metadata_extraction", "classification", "detection", "knowledge_pack_execution" -> 2L
            else -> 4L
        }
        return (modelSize * multiplier).coerceAtLeast(16L * 1024L * 1024L)
    }
}

class LocalAiExecutionScheduler(
    private val queue: LocalAiExecutionQueue,
    private val dispatcher: LocalAiTaskDispatcher,
    private val settingsProvider: () -> AiSettings,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
) {
    private val schedulerMutex = Mutex()
    private val activeJobs = ConcurrentHashMap<String, Job>()

    @Volatile
    private var schedulerPaused = false

    @Volatile
    private var schedulerStarted = false

    private var schedulerJob: Job? = null

    fun start() {
        resume()
    }

    fun pause() {
        schedulerPaused = true
    }

    fun resume() {
        schedulerPaused = false
        if (schedulerStarted) {
            return
        }
        scope.launch {
            schedulerMutex.withLock {
                if (schedulerStarted) {
                    return@withLock
                }
                schedulerStarted = true
            }
            schedulerJob = launchSchedulerLoop()
        }
    }

    fun enqueue(
        taskType: String,
        modelId: String = "",
        version: String = "",
        runtimeHint: String = "",
        priority: Int = 0,
        maxRetries: Int = settingsProvider().maxQueueRetries,
        timeoutMs: Long = settingsProvider().defaultTaskTimeoutMs,
        dependencyTaskIds: List<String> = emptyList(),
        payload: Map<String, Any> = emptyMap(),
    ): AiTaskRecord {
        val task = queue.enqueueTask(
            taskType = taskType,
            modelId = modelId,
            version = version,
            runtimeHint = runtimeHint,
            priority = priority,
            maxRetries = maxRetries,
            timeoutMs = timeoutMs,
            dependencyTaskIds = dependencyTaskIds,
            payload = payload,
        )
        resume()
        return task
    }

    fun listTasks(limit: Int = 200): List<AiTaskRecord> {
        return queue.listTasks(limit)
    }

    fun cancelTask(taskId: String): Boolean {
        return queue.cancelTask(taskId)
    }

    fun pauseTask(taskId: String): Boolean {
        return queue.pauseTask(taskId)
    }

    fun resumeTask(taskId: String): Boolean {
        val resumed = queue.resumeTask(taskId)
        if (resumed) {
            resume()
        }
        return resumed
    }

    fun retryTask(taskId: String): Boolean {
        val retried = queue.retryTask(taskId)
        if (retried) {
            resume()
        }
        return retried
    }

    private fun launchSchedulerLoop(): Job {
        return scope.launch {
            try {
                queue.recoverInterruptedTasks()
                while (isActive) {
                    if (schedulerPaused) {
                        delay(settingsProvider().schedulerPollIntervalMs)
                        continue
                    }

                    cleanupInactiveJobs()
                    val maxConcurrentTasks = settingsProvider().maxConcurrentTasks.coerceAtLeast(1)
                    if (activeJobs.size >= maxConcurrentTasks) {
                        delay(settingsProvider().schedulerPollIntervalMs)
                        continue
                    }

                    val launchSlots = (maxConcurrentTasks - activeJobs.size).coerceAtLeast(1)
                    val candidates = queue.listRunnableTasks(
                        nowMs = System.currentTimeMillis(),
                        limit = launchSlots * 4,
                    )

                    var launched = 0
                    candidates.forEach { task ->
                        if (launched >= launchSlots) {
                            return@forEach
                        }
                        if (activeJobs.containsKey(task.taskId)) {
                            return@forEach
                        }

                        when (resolveDependencyState(task)) {
                            DependencyState.BLOCKED_WAITING -> return@forEach
                            DependencyState.BLOCKED_FAILED -> {
                                queue.markTaskCompleted(
                                    taskId = task.taskId,
                                    status = "failed",
                                    result = mapOf(
                                        "status" to "failed",
                                        "message" to "Task dependency failed",
                                        "dependency_task_ids" to task.dependencyTaskIds,
                                    ),
                                    errorMessage = "Task dependency failed",
                                )
                                return@forEach
                            }

                            DependencyState.READY -> Unit
                        }

                        val job = scope.launch {
                            dispatcher.dispatch(task)
                        }
                        activeJobs[task.taskId] = job
                        job.invokeOnCompletion {
                            activeJobs.remove(task.taskId)
                        }
                        launched += 1
                    }

                    if (launched > 0) {
                        delay(settingsProvider().schedulerPollIntervalMs)
                    } else {
                        delay(settingsProvider().schedulerIdleDelayMs)
                    }
                }
            } finally {
                schedulerMutex.withLock {
                    schedulerStarted = false
                }
            }
        }
    }

    private fun cleanupInactiveJobs() {
        val finishedTaskIds = activeJobs.entries
            .filter { (_, job) -> !job.isActive }
            .map { (taskId, _) -> taskId }
        finishedTaskIds.forEach { activeJobs.remove(it) }
    }

    private fun resolveDependencyState(task: AiTaskRecord): DependencyState {
        if (task.dependencyTaskIds.isEmpty()) {
            return DependencyState.READY
        }
        val statuses = queue.listDependencyStatuses(task)
        task.dependencyTaskIds.forEach { dependencyTaskId ->
            val dependencyStatus = statuses[dependencyTaskId] ?: return DependencyState.BLOCKED_FAILED
            if (dependencyStatus in setOf("failed", "cancelled")) {
                return DependencyState.BLOCKED_FAILED
            }
            if (dependencyStatus != "succeeded") {
                return DependencyState.BLOCKED_WAITING
            }
        }
        return DependencyState.READY
    }

    private enum class DependencyState {
        READY,
        BLOCKED_WAITING,
        BLOCKED_FAILED,
    }
}

class LocalHeuristicAiBackend(
    override val runtimeId: String = "local_heuristic",
) : AiBackendRuntime {
    override val runtimeType: AiRuntimeType = AiRuntimeType.CUSTOM
    override val supportedTasks: Set<String> = AiTaskTypes.EXECUTION_TASKS

    override fun detectCapabilities(): AiBackendCapability {
        return AiBackendCapability(
            runtimeId = runtimeId,
            runtimeType = runtimeType,
            supportedTasks = supportedTasks,
            supportsCancellation = false,
            supportsPauseResume = false,
            maxConcurrentTasks = 1,
            metadata = mapOf(
                "provider" to "LocalHeuristicAiBackend",
                "mode" to "deterministic",
                "embedding_dim" to EMBEDDING_DIM,
            ),
        )
    }

    override suspend fun execute(request: AiExecutionRequest, reporter: AiProgressReporter): AiExecutionResult {
        val normalizedTaskType = AiTaskTypes.normalize(request.taskType)
        return when (normalizedTaskType) {
            "embedding_generation" -> executeEmbeddingGeneration(request, reporter)
            "similarity_search" -> executeSimilaritySearch(request, reporter)
            "ocr" -> executeOcr(request, reporter)
            "captioning" -> executeCaptioning(request, reporter)
            "metadata_extraction" -> executeMetadataExtraction(request, reporter)
            "character_recognition" -> executeRecognition(request, reporter, entityType = "character")
            "series_recognition" -> executeRecognition(request, reporter, entityType = "series")
            "artist_recognition" -> executeRecognition(request, reporter, entityType = "artist")
            "tag_prediction" -> executeTagPrediction(request, reporter)
            "prompt_generation" -> executePromptGeneration(request, reporter)
            "duplicate_detection" -> executeDuplicateDetection(request, reporter)
            "classification" -> executeClassification(request, reporter)
            "detection" -> executeDetection(request, reporter)
            "face_feature_extraction" -> executeFaceFeatureExtraction(request, reporter)
            "knowledge_pack_execution" -> executeKnowledgePackExecution(request, reporter)
            else -> executeGenericTask(request, reporter, normalizedTaskType)
        }
    }

    private suspend fun executeEmbeddingGeneration(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.15, "Preparing embedding payload")
        val text = buildDocumentText(request.payload)
        val embedding = embeddingOf(text)
        reporter.report(1.0, "Embedding generated")

        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Embedding generated locally",
            details = mapOf(
                "task_type" to "embedding_generation",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "text_length" to text.length,
                    "embedding_dim" to embedding.size,
                    "text" to text,
                ),
            ),
        )
    }

    private suspend fun executeSimilaritySearch(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.1, "Preparing semantic candidates")

        val queryText = request.payload.firstNonBlankString("query", "text", "prompt")
        val queryEmbedding = request.payload.numberList("query_embedding").takeIf { it.isNotEmpty() }
            ?: embeddingOf(queryText)
        val queryTokens = tokenize(queryText).toSet()

        val rawCandidates = (request.payload["candidates"] as? List<*>) ?: emptyList<Any>()
        val scoredCandidates = rawCandidates.mapNotNull { rawCandidate ->
            val candidateMap = rawCandidate.asStringAnyMap()
            val imageId = candidateMap["image_id"].toIntOrNullValue() ?: return@mapNotNull null
            val candidateText = candidateMap.firstNonBlankString("text", "caption", "filename", "path")
            val candidateEmbedding = candidateMap.numberList("embedding").takeIf { it.isNotEmpty() }
                ?: embeddingOf(candidateText)
            val cosine = cosineSimilarity(queryEmbedding, candidateEmbedding)
            val lexical = lexicalOverlap(queryTokens, tokenize(candidateText).toSet())
            val ratingBoost = ((candidateMap["rating"].toDoubleOrNullValue() ?: 0.0) / 5.0).coerceIn(0.0, 1.0) * 0.03
            val favoriteBoost = if (candidateMap["favorite"].toBooleanValue(defaultValue = false)) 0.02 else 0.0
            val score = (0.8 * cosine + 0.2 * lexical + ratingBoost + favoriteBoost)
                .coerceIn(-1.0, 1.0)

            ScoredCandidate(
                imageId = imageId,
                score = score,
                cosine = cosine,
                lexical = lexical,
            )
        }

        reporter.report(0.8, "Ranking semantic candidates")
        val topK = request.payload["top_k"].toIntOrNullValue()
            ?.coerceAtLeast(1)
            ?: scoredCandidates.size.coerceAtLeast(1)
        val ranked = scoredCandidates
            .sortedByDescending { it.score }
            .take(topK)
            .mapIndexed { index, candidate ->
                mapOf(
                    "image_id" to candidate.imageId,
                    "score" to candidate.score,
                    "cosine" to candidate.cosine,
                    "lexical" to candidate.lexical,
                    "rank" to (index + 1),
                )
            }

        reporter.report(1.0, "Semantic ranking complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Similarity search completed locally",
            details = mapOf(
                "task_type" to "similarity_search",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to queryEmbedding,
                "matches" to ranked,
                "result" to mapOf(
                    "query" to queryText,
                    "matches" to ranked,
                    "query_embedding_dim" to queryEmbedding.size,
                    "hybrid_weights" to mapOf(
                        "cosine" to 0.8,
                        "lexical" to 0.2,
                    ),
                ),
            ),
        )
    }

    private suspend fun executeOcr(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.2, "Extracting text candidates")
        val source = buildDocumentText(request.payload)
        val tokens = tokenize(source).filter { it.length > 1 }
        val lines = tokens.chunked(8).take(8).map { chunk -> chunk.joinToString(" ") }
        val extractedText = lines.joinToString("\n").ifBlank { source }
        val confidence = (0.45 + minOf(0.45, tokens.size / 40.0)).coerceIn(0.1, 0.9)
        val embedding = embeddingOf(extractedText)

        reporter.report(1.0, "OCR extraction complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "OCR pipeline completed locally",
            details = mapOf(
                "task_type" to "ocr",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "text" to extractedText,
                    "lines" to lines,
                    "confidence" to confidence,
                    "token_count" to tokens.size,
                ),
            ),
        )
    }

    private suspend fun executeCaptioning(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.2, "Building caption context")
        val metadata = request.payload["metadata"].asStringAnyMap()
        val tags = collectTags(request.payload)
        val orientation = metadata["orientation"]?.toString().orEmpty()
        val resolution = metadata["resolution"]?.toString().orEmpty().ifBlank {
            val width = metadata["width"].toIntOrNullValue()
            val height = metadata["height"].toIntOrNullValue()
            if (width != null && height != null && width > 0 && height > 0) "${width}x${height}" else ""
        }
        val subject = chooseSubject(tags, request.payload)
        val style = chooseStyle(tags)
        val caption = buildList {
            add(if (subject.isBlank()) "Illustration" else "Illustration of $subject")
            if (style.isNotBlank()) add("in a $style style")
            if (orientation.isNotBlank()) add("$orientation composition")
            if (resolution.isNotBlank()) add("at $resolution")
            if (tags.isNotEmpty()) add("keywords ${tags.take(5).joinToString(", ")}")
        }.joinToString(", ") + "."
        val embedding = embeddingOf(caption)

        reporter.report(1.0, "Captioning complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Captioning pipeline completed locally",
            details = mapOf(
                "task_type" to "captioning",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "caption" to caption,
                    "subject" to subject,
                    "style" to style,
                    "keywords" to tags.take(8),
                    "confidence" to (0.5 + minOf(0.35, tags.size / 20.0)),
                ),
            ),
        )
    }

    private suspend fun executeMetadataExtraction(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.2, "Extracting metadata fields")
        val metadata = request.payload["metadata"].asStringAnyMap().toMutableMap()
        metadata.putIfAbsent("image_id", request.payload["image_id"]?.toString().orEmpty())
        metadata.putIfAbsent("filename", request.payload["filename"]?.toString().orEmpty())
        metadata.putIfAbsent("path", request.payload["path"]?.toString().orEmpty())
        metadata.putIfAbsent("folder_uri", request.payload["folder_uri"]?.toString().orEmpty())

        if (!metadata.containsKey("extension") || metadata["extension"].toString().isBlank()) {
            val extension = metadata["filename"]?.toString().orEmpty().substringAfterLast('.', "").lowercase()
            if (extension.isNotBlank()) {
                metadata["extension"] = extension
            }
        }
        if (!metadata.containsKey("resolution") || metadata["resolution"].toString().isBlank()) {
            val width = metadata["width"].toIntOrNullValue()
            val height = metadata["height"].toIntOrNullValue()
            if (width != null && height != null && width > 0 && height > 0) {
                metadata["resolution"] = "${width}x${height}"
            }
        }

        val tags = collectTags(request.payload)
        if (tags.isNotEmpty()) {
            metadata["tags"] = tags
        }
        metadata["extracted_at_ms"] = System.currentTimeMillis()

        val metadataText = metadata.entries.joinToString(" ") { "${it.key}:${it.value}" }
        val embedding = embeddingOf(metadataText)

        reporter.report(1.0, "Metadata extraction complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Metadata extraction completed locally",
            details = mapOf(
                "task_type" to "metadata_extraction",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "metadata" to metadata,
                    "field_count" to metadata.size,
                ),
            ),
        )
    }

    private suspend fun executeRecognition(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
        entityType: String,
    ): AiExecutionResult {
        reporter.report(0.25, "Running $entityType recognition")
        val hints = collectEntityHints(entityType, request.payload)
        val candidates = hints.take(6).mapIndexed { index, value ->
            val confidence = (0.82 - (index * 0.09)).coerceAtLeast(0.3)
            mapOf(
                "name" to prettifyLabel(value),
                "confidence" to confidence,
                "source" to "heuristic",
            )
        }
        val topMatch = candidates.firstOrNull()?.get("name")?.toString().orEmpty()
        val embedding = embeddingOf(candidates.joinToString(" ") { it["name"].toString() })

        reporter.report(1.0, "$entityType recognition complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "$entityType recognition completed locally",
            details = mapOf(
                "task_type" to "${entityType}_recognition",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "entity_type" to entityType,
                    "top_match" to topMatch,
                    "candidates" to candidates,
                ),
            ),
        )
    }

    private suspend fun executeTagPrediction(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.2, "Scoring predicted tags")
        val frequency = linkedMapOf<String, Double>()
        collectTags(request.payload).forEach { tag ->
            val normalized = normalizeTag(tag)
            if (normalized.isBlank()) {
                return@forEach
            }
            frequency[normalized] = (frequency[normalized] ?: 0.0) + 2.0
        }
        tokenize(buildDocumentText(request.payload)).forEach { token ->
            val normalized = normalizeTag(token)
            if (normalized.length < 3 || normalized in STOP_WORDS) {
                return@forEach
            }
            frequency[normalized] = (frequency[normalized] ?: 0.0) + 1.0
        }

        val ranked = frequency.entries
            .sortedByDescending { it.value }
            .take(12)
        val maxScore = ranked.firstOrNull()?.value ?: 1.0
        val tags = ranked.map { it.key }
        val scoredTags = ranked.map { entry ->
            mapOf(
                "tag" to entry.key,
                "score" to (entry.value / maxScore).coerceIn(0.0, 1.0),
            )
        }
        val embedding = embeddingOf(tags.joinToString(" "))

        reporter.report(1.0, "Tag prediction complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Tag prediction completed locally",
            details = mapOf(
                "task_type" to "tag_prediction",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "tags" to tags,
                    "scored_tags" to scoredTags,
                ),
            ),
        )
    }

    private suspend fun executePromptGeneration(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.2, "Composing prompt context")
        val upstream = request.payload["upstream_results"].asStringAnyMap()
        val caption = extractStageString(upstream, "captioning", "caption")
            .ifBlank { request.payload.firstNonBlankString("caption", "text", "prompt") }
        val tags = extractStageTags(upstream, "tag_prediction")
            .ifEmpty { collectTags(request.payload) }
        val character = extractStageString(upstream, "character_recognition", "top_match")
        val series = extractStageString(upstream, "series_recognition", "top_match")
        val artist = extractStageString(upstream, "artist_recognition", "top_match")

        val subjectParts = listOf(character, series).filter { it.isNotBlank() }
        val subject = if (subjectParts.isNotEmpty()) subjectParts.joinToString(" from ") else "illustration"
        val prompt = buildList {
            add(caption.ifBlank { "Detailed $subject" })
            if (artist.isNotBlank()) add("inspired by $artist")
            if (tags.isNotEmpty()) add("tags: ${tags.take(10).joinToString(", ")}")
            add("high detail, clean composition")
        }.joinToString(", ")

        val negativePrompt = request.payload.firstNonBlankString("negative_prompt")
            .ifBlank { "lowres, blurry, artifacts, watermark" }
        val embedding = embeddingOf(prompt)

        reporter.report(1.0, "Prompt generation complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Prompt generation completed locally",
            details = mapOf(
                "task_type" to "prompt_generation",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "prompt" to prompt,
                    "negative_prompt" to negativePrompt,
                    "context" to mapOf(
                        "caption" to caption,
                        "character" to character,
                        "series" to series,
                        "artist" to artist,
                        "tags" to tags,
                    ),
                ),
            ),
        )
    }

    private suspend fun executeDuplicateDetection(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.15, "Preparing duplicate candidates")
        val threshold = request.payload["similarity_threshold"].toDoubleOrNullValue()?.coerceIn(0.6, 0.999) ?: 0.92
        val candidates = buildDuplicateCandidates(request.payload)

        if (candidates.size < 2) {
            return AiExecutionResult(
                ok = true,
                status = "succeeded",
                message = "Duplicate detection completed with insufficient candidates",
                details = mapOf(
                    "task_type" to "duplicate_detection",
                    "model_id" to request.modelId,
                    "model_version" to request.version,
                    "result" to mapOf(
                        "groups" to emptyList<Map<String, Any>>(),
                        "threshold" to threshold,
                        "candidate_count" to candidates.size,
                    ),
                ),
            )
        }

        val parent = IntArray(candidates.size) { it }
        fun find(x: Int): Int {
            var node = x
            while (parent[node] != node) {
                parent[node] = parent[parent[node]]
                node = parent[node]
            }
            return node
        }
        fun union(a: Int, b: Int) {
            val rootA = find(a)
            val rootB = find(b)
            if (rootA != rootB) {
                parent[rootB] = rootA
            }
        }

        var comparedPairs = 0
        val strongPairs = mutableListOf<Map<String, Any>>()
        for (left in candidates.indices) {
            for (right in (left + 1) until candidates.size) {
                comparedPairs += 1
                val score = cosineSimilarity(candidates[left].embedding, candidates[right].embedding)
                if (score >= threshold) {
                    union(left, right)
                    strongPairs += mapOf(
                        "left_image_id" to candidates[left].imageId,
                        "right_image_id" to candidates[right].imageId,
                        "score" to score,
                    )
                }
            }
        }

        reporter.report(0.85, "Grouping duplicate clusters")
        val grouped = linkedMapOf<Int, MutableList<DuplicateCandidate>>()
        candidates.forEachIndexed { index, candidate ->
            val root = find(index)
            grouped.getOrPut(root) { mutableListOf() }.add(candidate)
        }
        val groups = grouped.values
            .filter { it.size > 1 }
            .sortedByDescending { it.size }
            .mapIndexed { index, members ->
                val sortedMembers = members.sortedBy { it.imageId }
                mapOf(
                    "group_id" to "duplicate_${index + 1}",
                    "canonical_image_id" to sortedMembers.first().imageId,
                    "members" to sortedMembers.map { member ->
                        mapOf(
                            "image_id" to member.imageId,
                            "text" to member.text,
                        )
                    },
                    "size" to sortedMembers.size,
                )
            }

        reporter.report(1.0, "Duplicate detection complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Duplicate detection completed locally",
            details = mapOf(
                "task_type" to "duplicate_detection",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "result" to mapOf(
                    "groups" to groups,
                    "threshold" to threshold,
                    "candidate_count" to candidates.size,
                    "compared_pairs" to comparedPairs,
                    "duplicate_pairs" to strongPairs,
                ),
            ),
        )
    }

    private suspend fun executeClassification(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.2, "Computing classification scores")
        val metadata = request.payload["metadata"].asStringAnyMap()
        val tags = collectTags(request.payload)
        val tokens = (tags + tokenize(buildDocumentText(request.payload))).map { it.lowercase() }

        val scores = linkedMapOf(
            "portrait" to 0.2,
            "landscape" to 0.2,
            "illustration" to 0.2,
            "comic" to 0.15,
            "character_sheet" to 0.1,
            "concept_art" to 0.15,
        )

        val orientation = metadata["orientation"]?.toString()?.lowercase().orEmpty()
        if (orientation == "portrait") {
            scores["portrait"] = (scores["portrait"] ?: 0.0) + 0.4
        }
        if (orientation == "landscape") {
            scores["landscape"] = (scores["landscape"] ?: 0.0) + 0.4
        }

        tokens.forEach { token ->
            when {
                token in setOf("portrait", "headshot", "bust") -> scores["portrait"] = (scores["portrait"] ?: 0.0) + 0.35
                token in setOf("landscape", "scenery", "background") -> scores["landscape"] = (scores["landscape"] ?: 0.0) + 0.35
                token in setOf("comic", "manga", "panel") -> scores["comic"] = (scores["comic"] ?: 0.0) + 0.35
                token in setOf("sheet", "turnaround", "reference") -> scores["character_sheet"] = (scores["character_sheet"] ?: 0.0) + 0.35
                token in setOf("concept", "design", "ideation") -> scores["concept_art"] = (scores["concept_art"] ?: 0.0) + 0.25
                else -> scores["illustration"] = (scores["illustration"] ?: 0.0) + 0.03
            }
        }

        val total = scores.values.sum().coerceAtLeast(1e-9)
        val rankedLabels = scores.entries
            .map { entry ->
                mapOf(
                    "label" to entry.key,
                    "score" to (entry.value / total).coerceIn(0.0, 1.0),
                )
            }
            .sortedByDescending { it["score"] as Double }
        val topLabel = rankedLabels.firstOrNull()?.get("label")?.toString().orEmpty()
        val embedding = embeddingOf(topLabel)

        reporter.report(1.0, "Classification complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Classification completed locally",
            details = mapOf(
                "task_type" to "classification",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "label" to topLabel,
                    "ranked_labels" to rankedLabels,
                ),
            ),
        )
    }

    private suspend fun executeDetection(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.2, "Deriving detection windows")
        val metadata = request.payload["metadata"].asStringAnyMap()
        val width = metadata["width"].toIntOrNullValue() ?: request.payload["width"].toIntOrNullValue() ?: 0
        val height = metadata["height"].toIntOrNullValue() ?: request.payload["height"].toIntOrNullValue() ?: 0
        val tokens = (collectTags(request.payload) + tokenize(buildDocumentText(request.payload))).map { it.lowercase() }

        val detections = mutableListOf<Map<String, Any>>()
        if (width > 0 && height > 0) {
            if (tokens.any { it in setOf("face", "character", "person", "portrait") }) {
                detections += mapOf(
                    "label" to "character",
                    "confidence" to 0.72,
                    "bbox" to mapOf(
                        "x" to (width * 0.28).toInt(),
                        "y" to (height * 0.12).toInt(),
                        "w" to (width * 0.44).toInt(),
                        "h" to (height * 0.62).toInt(),
                    ),
                )
            }
            if (tokens.any { it in setOf("text", "speech", "caption", "logo") }) {
                detections += mapOf(
                    "label" to "text_region",
                    "confidence" to 0.58,
                    "bbox" to mapOf(
                        "x" to (width * 0.08).toInt(),
                        "y" to (height * 0.05).toInt(),
                        "w" to (width * 0.84).toInt(),
                        "h" to (height * 0.2).toInt(),
                    ),
                )
            }
            if (detections.isEmpty() && tokens.isNotEmpty()) {
                detections += mapOf(
                    "label" to "scene",
                    "confidence" to 0.25,
                    "bbox" to mapOf(
                        "x" to 0,
                        "y" to 0,
                        "w" to width,
                        "h" to height,
                    ),
                )
            }
        }
        val embedding = embeddingOf(detections.joinToString(" ") { it["label"].toString() })

        reporter.report(1.0, "Detection complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Detection pipeline completed locally",
            details = mapOf(
                "task_type" to "detection",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "detections" to detections,
                    "image_size" to mapOf("width" to width, "height" to height),
                    "detector" to "local_heuristic",
                ),
            ),
        )
    }

    private suspend fun executeFaceFeatureExtraction(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.2, "Computing face feature embeddings")
        val metadata = request.payload["metadata"].asStringAnyMap()
        val width = metadata["width"].toIntOrNullValue() ?: request.payload["width"].toIntOrNullValue() ?: 0
        val height = metadata["height"].toIntOrNullValue() ?: request.payload["height"].toIntOrNullValue() ?: 0
        val detections = request.payload["detections"].asListOfMaps().toMutableList()
        if (detections.isEmpty() && width > 0 && height > 0) {
            detections += mapOf(
                "label" to "face",
                "confidence" to 0.5,
                "bbox" to mapOf(
                    "x" to (width * 0.3).toInt(),
                    "y" to (height * 0.18).toInt(),
                    "w" to (width * 0.4).toInt(),
                    "h" to (height * 0.4).toInt(),
                ),
            )
        }

        val baseText = "face ${buildDocumentText(request.payload)} count:${detections.size}"
        val featureVector = embeddingOf(baseText)

        reporter.report(1.0, "Face feature extraction complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Face feature extraction completed locally",
            details = mapOf(
                "task_type" to "face_feature_extraction",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to featureVector,
                "result" to mapOf(
                    "face_count" to detections.size,
                    "detections" to detections,
                    "feature_vector" to featureVector,
                ),
            ),
        )
    }

    private suspend fun executeKnowledgePackExecution(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
    ): AiExecutionResult {
        reporter.report(0.2, "Validating knowledge pack request")
        val packId = request.payload.firstNonBlankString("knowledge_pack_id", "pack_id", "id").ifBlank { "default_pack" }
        val version = request.payload.firstNonBlankString("knowledge_pack_version", "version").ifBlank { "1.0.0" }
        val operations = request.payload["operations"].toStringList()
            .ifEmpty { request.payload["stages"].toStringList() }
            .ifEmpty { listOf("validate", "execute") }

        val startedAt = System.currentTimeMillis()
        val operationResults = operations.mapIndexed { index, operation ->
            mapOf(
                "operation" to operation,
                "index" to (index + 1),
                "status" to "succeeded",
                "started_at_ms" to startedAt,
                "completed_at_ms" to (startedAt + (index + 1) * 5L),
            )
        }
        val embedding = embeddingOf("$packId ${operations.joinToString(" ")}")

        reporter.report(1.0, "Knowledge pack execution complete")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Knowledge pack execution completed locally",
            details = mapOf(
                "task_type" to "knowledge_pack_execution",
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to mapOf(
                    "knowledge_pack_id" to packId,
                    "knowledge_pack_version" to version,
                    "operations" to operationResults,
                    "dependencies" to request.payload["dependencies"].toStringList(),
                    "rollback_supported" to request.payload["rollback_supported"].toBooleanValue(defaultValue = true),
                ),
            ),
        )
    }

    private suspend fun executeGenericTask(
        request: AiExecutionRequest,
        reporter: AiProgressReporter,
        normalizedTaskType: String,
    ): AiExecutionResult {
        reporter.report(0.25, "Preparing local $normalizedTaskType result")
        val summaryText = buildDocumentText(request.payload)
        val summary = mapOf(
            "acknowledged" to true,
            "summary_text" to summaryText,
            "token_count" to tokenize(summaryText).size,
        )
        val embedding = embeddingOf(summaryText)

        reporter.report(1.0, "Completed local $normalizedTaskType")
        return AiExecutionResult(
            ok = true,
            status = "succeeded",
            message = "Task $normalizedTaskType completed locally",
            details = mapOf(
                "task_type" to normalizedTaskType,
                "model_id" to request.modelId,
                "model_version" to request.version,
                "embedding" to embedding,
                "result" to summary,
            ),
        )
    }

    private fun buildDocumentText(payload: Map<String, Any>): String {
        val metadata = payload["metadata"].asStringAnyMap()
        val parts = mutableListOf<String>()
        parts += payload.firstNonBlankString("text", "query", "prompt", "caption", "ocr_text", "hint")
        parts += payload["filename"]?.toString().orEmpty()
        parts += payload["path"]?.toString().orEmpty()
        parts += payload["folder_uri"]?.toString().orEmpty()
        parts += metadata["metadata_text"]?.toString().orEmpty()
        parts += metadata["taxonomy_text"]?.toString().orEmpty()
        parts += metadata["folder_name"]?.toString().orEmpty()
        parts += metadata["relative_path"]?.toString().orEmpty()
        val tags = collectTags(payload)
        if (tags.isNotEmpty()) {
            parts += tags.joinToString(" ")
        }
        return parts
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .joinToString(" ")
            .trim()
    }

    private fun collectTags(payload: Map<String, Any>): List<String> {
        val metadata = payload["metadata"].asStringAnyMap()
        val tags = linkedSetOf<String>()
        payload["tags"].toStringList().forEach { tags += normalizeTag(it) }
        metadata["tags"].toStringList().forEach { tags += normalizeTag(it) }
        metadata["user_tags"].toStringList().forEach { tags += normalizeTag(it) }
        return tags.filter { it.isNotBlank() }
    }

    private fun chooseSubject(tags: List<String>, payload: Map<String, Any>): String {
        val prioritized = tags.firstOrNull { it !in STOP_WORDS }
        if (!prioritized.isNullOrBlank()) {
            return prettifyLabel(prioritized)
        }
        val filename = payload["filename"]?.toString().orEmpty()
        val fallback = tokenize(filename).firstOrNull { it.length > 2 && it !in STOP_WORDS }
        return fallback?.let { prettifyLabel(it) }.orEmpty()
    }

    private fun chooseStyle(tags: List<String>): String {
        val styleKeywords = listOf("anime", "manga", "pixel", "watercolor", "sketch", "realistic", "comic")
        return tags.firstOrNull { tag -> styleKeywords.any { tag.contains(it) } }?.let { prettifyLabel(it) }.orEmpty()
    }

    private fun collectEntityHints(entityType: String, payload: Map<String, Any>): List<String> {
        val metadata = payload["metadata"].asStringAnyMap()
        val taxonomy = parseTaxonomy(metadata["taxonomy_text"]?.toString().orEmpty())
        val tags = collectTags(payload)

        val keyAliases = when (entityType) {
            "character" -> setOf("character", "char")
            "series" -> setOf("series", "franchise", "title")
            "artist" -> setOf("artist", "creator", "author")
            else -> setOf(entityType)
        }

        val values = linkedSetOf<String>()
        taxonomy.forEach { (key, entries) ->
            if (key in keyAliases) {
                entries.forEach { values += normalizeTag(it) }
            }
        }

        tags.forEach { tag ->
            val key = tag.substringBefore(':').substringBefore('=').trim().lowercase()
            val value = tag.substringAfter(':', "").substringAfter('=', "").trim()
            if (key in keyAliases && value.isNotBlank()) {
                values += normalizeTag(value)
            }
        }

        if (values.isEmpty()) {
            tokenize(buildDocumentText(payload)).forEach { token ->
                if (token.length >= 3 && token !in STOP_WORDS) {
                    values += token
                }
            }
        }

        return values.filter { it.isNotBlank() }
    }

    private fun parseTaxonomy(text: String): Map<String, List<String>> {
        if (text.isBlank()) {
            return emptyMap()
        }
        val values = linkedMapOf<String, MutableList<String>>()
        text.split('|', ';', '\n').forEach { rawEntry ->
            val entry = rawEntry.trim()
            if (entry.isBlank()) {
                return@forEach
            }
            val idx = entry.indexOf('=')
            if (idx <= 0 || idx >= entry.lastIndex) {
                return@forEach
            }
            val key = entry.substring(0, idx).trim().lowercase()
            val value = entry.substring(idx + 1).trim()
            if (key.isBlank() || value.isBlank()) {
                return@forEach
            }
            values.getOrPut(key) { mutableListOf() }.add(value)
        }
        return values.mapValues { (_, entries) -> entries.map { normalizeTag(it) }.filter { it.isNotBlank() }.distinct() }
    }

    private fun normalizeTag(tag: String): String {
        return tag
            .trim()
            .lowercase()
            .replace(Regex("[^a-z0-9:_=\\- ]"), " ")
            .replace('-', ' ')
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    private fun prettifyLabel(raw: String): String {
        return raw
            .replace('_', ' ')
            .replace('-', ' ')
            .split(' ')
            .filter { it.isNotBlank() }
            .joinToString(" ") { part -> part.replaceFirstChar { ch -> ch.uppercase() } }
            .trim()
    }

    private fun extractStageString(upstreamResults: Map<String, Any>, stage: String, key: String): String {
        val stageResult = upstreamResults[stage].asStringAnyMap()
        val nested = stageResult["result"].asStringAnyMap()
        return nested[key]?.toString().orEmpty().ifBlank { stageResult[key]?.toString().orEmpty() }
    }

    private fun extractStageTags(upstreamResults: Map<String, Any>, stage: String): List<String> {
        val stageResult = upstreamResults[stage].asStringAnyMap()
        val nested = stageResult["result"].asStringAnyMap()
        return nested["tags"].toStringList().ifEmpty { stageResult["tags"].toStringList() }
    }

    private fun buildDuplicateCandidates(payload: Map<String, Any>): List<DuplicateCandidate> {
        val rows = (payload["candidates"] as? List<*>)?.mapNotNull { it.asStringAnyMap() } ?: emptyList()
        return rows.mapNotNull { row ->
            val imageId = row["image_id"].toIntOrNullValue() ?: return@mapNotNull null
            val text = row.firstNonBlankString("text", "caption", "filename", "path")
            val embedding = row.numberList("embedding").takeIf { it.isNotEmpty() } ?: embeddingOf(text)
            DuplicateCandidate(
                imageId = imageId,
                text = text,
                embedding = embedding,
            )
        }
    }

    private fun embeddingOf(text: String): List<Double> {
        val tokens = tokenize(text)
        if (tokens.isEmpty()) {
            return List(EMBEDDING_DIM) { 0.0 }
        }

        val vector = DoubleArray(EMBEDDING_DIM)
        tokens.forEachIndexed { index, token ->
            val hash = stableHash(token)
            val primary = ((hash and Int.MAX_VALUE) % EMBEDDING_DIM)
            val secondary = (((hash ushr 8) + (index * 31)) and Int.MAX_VALUE) % EMBEDDING_DIM
            val tertiary = ((token.length * 13 + index) and Int.MAX_VALUE) % EMBEDDING_DIM

            vector[primary] += 1.0
            vector[secondary] += 0.5
            vector[tertiary] += 0.25
        }
        return l2Normalize(vector)
    }

    private fun tokenize(text: String): List<String> {
        return TOKEN_REGEX.findAll(text.lowercase())
            .map { it.value }
            .toList()
    }

    private fun stableHash(value: String): Int {
        var hash = 0x811c9dc5.toInt()
        value.forEach { ch ->
            hash = hash xor ch.code
            hash *= 16777619
        }
        return hash
    }

    private fun l2Normalize(vector: DoubleArray): List<Double> {
        var sumSquares = 0.0
        vector.forEach { value ->
            sumSquares += value * value
        }
        if (sumSquares <= 0.0) {
            return vector.toList()
        }
        val norm = sqrt(sumSquares)
        return vector.map { it / norm }
    }

    private fun cosineSimilarity(left: List<Double>, right: List<Double>): Double {
        if (left.isEmpty() || right.isEmpty()) {
            return 0.0
        }
        val size = minOf(left.size, right.size)
        var dot = 0.0
        var leftNorm = 0.0
        var rightNorm = 0.0
        for (i in 0 until size) {
            val l = left[i]
            val r = right[i]
            dot += l * r
            leftNorm += l * l
            rightNorm += r * r
        }
        if (leftNorm <= 0.0 || rightNorm <= 0.0) {
            return 0.0
        }
        return dot / (sqrt(leftNorm) * sqrt(rightNorm))
    }

    private fun lexicalOverlap(queryTokens: Set<String>, candidateTokens: Set<String>): Double {
        if (queryTokens.isEmpty() || candidateTokens.isEmpty()) {
            return 0.0
        }
        val intersection = queryTokens.intersect(candidateTokens).size.toDouble()
        val union = queryTokens.union(candidateTokens).size.toDouble().coerceAtLeast(1.0)
        return (intersection / union).coerceIn(0.0, 1.0)
    }

    private fun Map<String, Any>.firstNonBlankString(vararg keys: String): String {
        keys.forEach { key ->
            val value = this[key]?.toString()?.trim().orEmpty()
            if (value.isNotBlank()) {
                return value
            }
        }
        return ""
    }

    private fun Map<String, Any>.numberList(key: String): List<Double> {
        val raw = this[key] as? List<*> ?: return emptyList()
        return raw.mapNotNull { it.toDoubleOrNullValue() }
    }

    private fun Any?.asStringAnyMap(): Map<String, Any> {
        val map = this as? Map<*, *> ?: return emptyMap()
        val result = linkedMapOf<String, Any>()
        map.forEach { (keyRaw, value) ->
            val key = keyRaw?.toString()?.trim().orEmpty()
            if (key.isBlank() || value == null) {
                return@forEach
            }
            result[key] = value
        }
        return result
    }

    private fun Any?.asListOfMaps(): List<Map<String, Any>> {
        val rawList = this as? List<*> ?: return emptyList()
        return rawList.mapNotNull { it.asStringAnyMap() }
    }

    private fun Any?.toStringList(): List<String> {
        return when (this) {
            is List<*> -> this.mapNotNull { it?.toString()?.trim() }.filter { it.isNotBlank() }
            is String -> this.split(',', '|', ';').map { it.trim() }.filter { it.isNotBlank() }
            else -> emptyList()
        }
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

    private fun Any?.toBooleanValue(defaultValue: Boolean): Boolean {
        return when (this) {
            is Boolean -> this
            is Number -> this.toInt() != 0
            else -> this?.toString()?.let { raw ->
                when (raw.trim().lowercase()) {
                    "true", "1", "yes", "on" -> true
                    "false", "0", "no", "off" -> false
                    else -> defaultValue
                }
            } ?: defaultValue
        }
    }

    private data class ScoredCandidate(
        val imageId: Int,
        val score: Double,
        val cosine: Double,
        val lexical: Double,
    )

    private data class DuplicateCandidate(
        val imageId: Int,
        val text: String,
        val embedding: List<Double>,
    )

    companion object {
        private const val EMBEDDING_DIM = 64
        private val TOKEN_REGEX = Regex("[a-z0-9_]+")
        private val STOP_WORDS = setOf(
            "the",
            "and",
            "for",
            "with",
            "from",
            "this",
            "that",
            "image",
            "illustration",
            "untitled",
            "file",
        )
    }
}