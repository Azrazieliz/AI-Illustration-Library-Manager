package com.ailm.android.runtime.ai

import android.content.Context
import android.util.Log
import com.ailm.android.runtime.LocalDatabase
import kotlinx.coroutines.CoroutineScope
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import org.json.JSONObject

class LocalAiManager(
    context: Context,
    database: LocalDatabase,
    scope: CoroutineScope,
) {
    private val appContext = context.applicationContext
    private val repository = LocalAiRepository(database)
    private val settingsManager = LocalAiSettingsManager(repository)
    private val hardwareDetector = LocalAiHardwareDetector(appContext)
    private val backendManager = LocalAiBackendManager()
    private val resourceManager = LocalAiResourceManager(
        hardwareProvider = { hardwareDetector.detectProfile() },
        settingsProvider = { settingsManager.getSettings() },
    )
    private val validationService = LocalAiValidationService(repository, backendManager, resourceManager)
    private val runtimeGateway = DefaultLocalAiRuntimeGateway(
        validationService = validationService,
    )
    private val runtimeSelector = LocalAiRuntimeSelector(
        settingsProvider = { settingsManager.getSettings() },
    )
    private val backendSelector = LocalAiBackendSelector(backendManager)
    private val resultValidator = LocalAiResultValidator()
    private val executionQueue = LocalAiExecutionQueue(
        repository = repository,
        settingsProvider = { settingsManager.getSettings() },
    )
    private val modelCache = LocalAiModelCache(repository)
    private val executionCache = LocalAiExecutionCache(appContext, modelCache)
    private val sessionCache = LocalAiSessionCache(modelCache)
    private val executionHistory = LocalAiExecutionHistory(repository)
    private val progressManager = LocalAiProgressManager(executionQueue, executionHistory)
    private val retryManager = LocalAiRetryManager { settingsManager.getSettings() }
    private val memoryManager = LocalAiMemoryManager(
        hardwareProvider = { hardwareDetector.detectProfile() },
        settingsProvider = { settingsManager.getSettings() },
    )
    private val modelLifetimeManager = LocalAiModelLifetimeManager(sessionCache)
    private val runtimeHealthMonitor = LocalAiRuntimeHealthMonitor(repository)
    private val taskDispatcher = LocalAiTaskDispatcher(
        queue = executionQueue,
        repository = repository,
        backendManager = backendManager,
        runtimeSelector = runtimeSelector,
        backendSelector = backendSelector,
        runtimeGateway = runtimeGateway,
        validationService = validationService,
        resultValidator = resultValidator,
        progressManager = progressManager,
        retryManager = retryManager,
        executionHistory = executionHistory,
        executionCache = executionCache,
        sessionCache = sessionCache,
        memoryManager = memoryManager,
        modelLifetimeManager = modelLifetimeManager,
        runtimeHealthMonitor = runtimeHealthMonitor,
        settingsProvider = { settingsManager.getSettings() },
    )
    private val executionScheduler = LocalAiExecutionScheduler(
        queue = executionQueue,
        dispatcher = taskDispatcher,
        settingsProvider = { settingsManager.getSettings() },
        scope = scope,
    )

    @Volatile
    private var initialized = false

    fun initialize() {
        if (initialized) {
            return
        }
        synchronized(this) {
            if (initialized) {
                return
            }
            bootstrapBuiltinBackend()
            bootstrapBuiltinSemanticModel()
            bootstrapAssetCapabilities()
            settingsManager.getSettings()
            executionScheduler.start()
            initialized = true
        }
    }

    fun executionChain(): Map<String, Any> {
        return mapOf(
            "entrypoint" to "StandaloneRuntime",
            "manager" to "LocalAiManager",
            "chain" to listOf(
                "StandaloneRuntime",
                "LocalAiManager",
                "LocalAiExecutionScheduler",
                "LocalAiExecutionQueue",
                "LocalAiRuntimeSelector",
                "LocalAiBackendSelector",
                "LocalAiTaskDispatcher",
                "LocalAiResultValidator",
                "LocalAiExecutionCache",
                "LocalAiRepository",
                "Caller",
            ),
            "module4_components" to mapOf(
                "ai_manager" to "LocalAiManager",
                "repository" to "LocalAiRepository",
                "schema" to "LocalAiSchema",
                "runtime_gateway" to "DefaultLocalAiRuntimeGateway",
                "backend_registry" to "LocalAiBackendManager",
                "queue" to "LocalAiExecutionQueue",
                "cache" to "LocalAiModelCache",
                "settings_manager" to "LocalAiSettingsManager",
                "hardware_detector" to "LocalAiHardwareDetector",
                "resource_manager" to "LocalAiResourceManager",
                "validation_service" to "LocalAiValidationService",
            ),
            "module5_components" to mapOf(
                "execution_scheduler" to "LocalAiExecutionScheduler",
                "task_dispatcher" to "LocalAiTaskDispatcher",
                "runtime_selector" to "LocalAiRuntimeSelector",
                "backend_selector" to "LocalAiBackendSelector",
                "execution_session" to "AiExecutionSessionRecord",
                "progress_manager" to "LocalAiProgressManager",
                "retry_manager" to "LocalAiRetryManager",
                "result_validator" to "LocalAiResultValidator",
                "execution_history" to "LocalAiExecutionHistory",
                "model_lifetime_manager" to "LocalAiModelLifetimeManager",
                "memory_manager" to "LocalAiMemoryManager",
                "execution_cache" to "LocalAiExecutionCache",
                "session_cache" to "LocalAiSessionCache",
                "runtime_health_monitor" to "LocalAiRuntimeHealthMonitor",
            ),
        )
    }

    fun overview(): Map<String, Any> {
        ensureInitialized()
        val available = repository.listModels(installedOnly = false).size
        val installed = repository.listModels(installedOnly = true).size
        val tasks = repository.listTasks(limit = 500)
        val cacheBytes = repository.totalCacheBytes()
        val plugins = repository.listPlugins().size
        val capabilities = repository.listCapabilities().size
        return mapOf(
            "status" to "ok",
            "available_models" to available,
            "installed_models" to installed,
            "queue_pending" to tasks.count { it.status == "pending" },
            "queue_running" to tasks.count { it.status == "running" },
            "queue_paused" to tasks.count { it.status == "paused" },
            "queue_failed" to tasks.count { it.status == "failed" },
            "cache_bytes" to cacheBytes,
            "plugins" to plugins,
            "capabilities" to capabilities,
            "backends" to backendManager.listBackends(),
            "execution_sessions" to repository.listExecutionSessions(limit = 500).size,
            "runtime_health_samples" to repository.listRuntimeHealthSnapshots(limit = 200).size,
            "execution_chain" to executionChain(),
        )
    }

    fun detectHardwareProfile(): Map<String, Any> {
        ensureInitialized()
        val profile = hardwareDetector.detectProfile()
        repository.saveHardwareProfile(profile)
        return profile.toMap()
    }

    fun latestHardwareProfile(): Map<String, Any> {
        ensureInitialized()
        val profile = repository.latestHardwareProfile() ?: hardwareDetector.detectProfile()
        return profile.toMap()
    }

    fun getSettings(): Map<String, Any> {
        ensureInitialized()
        return settingsManager.getSettings().toMap()
    }

    fun updateSettings(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        return settingsManager.updateSettings(payload).toMap()
    }

    fun listBackends(): List<Map<String, Any>> {
        ensureInitialized()
        return backendManager.listBackends()
    }

    fun registerAvailableModel(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val descriptor = payloadToModelDescriptor(
            payload = payload,
            installed = false,
            installState = payload["install_state"]?.toString()?.ifBlank { "available" } ?: "available",
            installPath = "",
        )
        val validation = validationService.validateModelDescriptor(descriptor)
        if (!validation.valid) {
            return mapOf(
                "ok" to false,
                "message" to "Model descriptor is invalid",
                "validation" to validation.toMap(),
            )
        }

        repository.upsertModel(descriptor)
        return mapOf(
            "ok" to true,
            "model" to descriptor.toMap(),
            "validation" to validation.toMap(),
        )
    }

    fun listAvailableModels(): List<Map<String, Any>> {
        ensureInitialized()
        return repository.listModels(installedOnly = false).map { it.toMap() }
    }

    fun listInstalledModels(): List<Map<String, Any>> {
        ensureInitialized()
        return repository.listModels(installedOnly = true).map { it.toMap() }
    }

    fun importLocalModel(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val modelId = payload["model_id"]?.toString()?.trim().orEmpty()
        val version = payload["version"]?.toString()?.trim().orEmpty().ifBlank { "1.0.0" }
        val sourcePath = payload["source_path"]?.toString()?.trim().orEmpty()
        if (modelId.isBlank() || sourcePath.isBlank()) {
            return mapOf(
                "ok" to false,
                "message" to "model_id and source_path are required",
            )
        }

        val sourceFile = File(sourcePath)
        if (!sourceFile.exists() || !sourceFile.isFile) {
            return mapOf(
                "ok" to false,
                "message" to "source_path does not exist: $sourcePath",
            )
        }

        val installId = UUID.randomUUID().toString()
        val now = System.currentTimeMillis()
        val expectedHash = payload["hash_sha256"]?.toString()?.trim().orEmpty().lowercase()

        repository.upsertInstallRun(
            AiInstallRunRecord(
                installId = installId,
                modelId = modelId,
                version = version,
                action = "local_import",
                sourceUri = sourcePath,
                expectedHash = expectedHash,
                actualHash = "",
                status = "running",
                details = payload,
                retryCount = 0,
                createdAtMs = now,
                startedAtMs = now,
                finishedAtMs = 0L,
                errorMessage = "",
            ),
        )

        return runCatching {
            val sizeBytes = sourceFile.length()
            val computedHash = sha256Hex(sourceFile)
            if (expectedHash.isNotBlank() && !computedHash.equals(expectedHash, ignoreCase = true)) {
                val details = mapOf(
                    "source_path" to sourcePath,
                    "size_bytes" to sizeBytes,
                )
                repository.updateInstallRun(
                    installId = installId,
                    status = "failed",
                    actualHash = computedHash,
                    details = details,
                    errorMessage = "SHA-256 mismatch",
                    retryCount = 0,
                    startedAtMs = now,
                    finishedAtMs = System.currentTimeMillis(),
                )
                return mapOf(
                    "ok" to false,
                    "message" to "SHA-256 mismatch",
                    "install_id" to installId,
                    "expected_hash" to expectedHash,
                    "actual_hash" to computedHash,
                )
            }

            val descriptor = payloadToModelDescriptor(
                payload = payload + mapOf(
                    "version" to version,
                    "size_bytes" to sizeBytes,
                    "hash_sha256" to computedHash,
                    "source_uri" to sourcePath,
                ),
                installed = true,
                installState = "installed",
                installPath = sourcePath,
            )

            val validation = validationService.validateModelDescriptor(descriptor)
            if (!validation.valid) {
                repository.updateInstallRun(
                    installId = installId,
                    status = "failed",
                    actualHash = computedHash,
                    details = validation.toMap(),
                    errorMessage = "Model descriptor validation failed",
                    retryCount = 0,
                    startedAtMs = now,
                    finishedAtMs = System.currentTimeMillis(),
                )
                return mapOf(
                    "ok" to false,
                    "message" to "Model descriptor validation failed",
                    "validation" to validation.toMap(),
                )
            }

            repository.upsertModel(descriptor)
            repository.updateInstallRun(
                installId = installId,
                status = "succeeded",
                actualHash = computedHash,
                details = mapOf(
                    "source_path" to sourcePath,
                    "size_bytes" to sizeBytes,
                    "imported_at_ms" to System.currentTimeMillis(),
                ),
                errorMessage = "",
                retryCount = 0,
                startedAtMs = now,
                finishedAtMs = System.currentTimeMillis(),
            )

            enqueueTask(
                payload = mapOf(
                    "task_type" to "metadata_refresh",
                    "model_id" to modelId,
                    "version" to version,
                    "priority" to 10,
                    "payload" to mapOf("trigger" to "local_import"),
                ),
            )

            mapOf(
                "ok" to true,
                "install_id" to installId,
                "model" to descriptor.toMap(),
            )
        }.getOrElse { error ->
            repository.updateInstallRun(
                installId = installId,
                status = "failed",
                actualHash = "",
                details = mapOf("source_path" to sourcePath),
                errorMessage = error.message ?: error.javaClass.simpleName,
                retryCount = 0,
                startedAtMs = now,
                finishedAtMs = System.currentTimeMillis(),
            )
            mapOf(
                "ok" to false,
                "install_id" to installId,
                "message" to (error.message ?: error.javaClass.simpleName),
            )
        }
    }

    fun registerModelDownload(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val modelId = payload["model_id"]?.toString()?.trim().orEmpty()
        val version = payload["version"]?.toString()?.trim().orEmpty().ifBlank { "1.0.0" }
        if (modelId.isBlank()) {
            return mapOf("ok" to false, "message" to "model_id is required")
        }

        val descriptor = payloadToModelDescriptor(
            payload = payload + mapOf("version" to version),
            installed = false,
            installState = "queued",
            installPath = "",
        )
        repository.upsertModel(descriptor)

        val installId = UUID.randomUUID().toString()
        val now = System.currentTimeMillis()
        repository.upsertInstallRun(
            AiInstallRunRecord(
                installId = installId,
                modelId = modelId,
                version = version,
                action = "download_registration",
                sourceUri = payload["source_uri"]?.toString().orEmpty(),
                expectedHash = descriptor.hashSha256,
                actualHash = "",
                status = "registered",
                details = payload,
                retryCount = 0,
                createdAtMs = now,
                startedAtMs = 0L,
                finishedAtMs = 0L,
                errorMessage = "",
            ),
        )

        val task = enqueueTask(
            payload = mapOf(
                "task_type" to "download_registration",
                "model_id" to modelId,
                "version" to version,
                "runtime_hint" to descriptor.requiredRuntime,
                "priority" to ((payload["priority"] as? Number)?.toInt() ?: 5),
                "payload" to payload,
            ),
        )

        return mapOf(
            "ok" to true,
            "install_id" to installId,
            "task" to task,
            "model" to descriptor.toMap(),
        )
    }

    fun removeModel(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val modelId = payload["model_id"]?.toString()?.trim().orEmpty()
        if (modelId.isBlank()) {
            return mapOf("ok" to false, "message" to "model_id is required")
        }
        val version = payload["version"]?.toString()?.trim().orEmpty()
        val deleteFile = payload["delete_file"].toBooleanValue(defaultValue = false)

        val target = if (version.isBlank()) {
            repository.listModels(installedOnly = true)
                .filter { it.modelId == modelId }
                .maxWithOrNull(compareBy<AiModelDescriptor> { it.version })
        } else {
            repository.getModel(modelId, version)
        }

        if (target == null) {
            return mapOf("ok" to false, "message" to "Model not found")
        }

        if (deleteFile && target.installPath.isNotBlank()) {
            runCatching {
                val file = File(target.installPath)
                if (file.exists() && file.isFile) {
                    file.delete()
                }
            }.onFailure {
                Log.w(TAG, "Failed to delete model file: ${target.installPath}", it)
            }
        }

        repository.setModelInstallState(
            modelId = target.modelId,
            version = target.version,
            installed = false,
            installState = "removed",
            installPath = "",
        )

        val cacheEntries = modelCache.listEntries(limit = 500).filter { it.modelId == target.modelId }
        cacheEntries.forEach { modelCacheEntry ->
            repository.removeCacheEntry(modelCacheEntry.cacheKey)
        }

        return mapOf(
            "ok" to true,
            "model_id" to target.modelId,
            "version" to target.version,
            "cache_entries_removed" to cacheEntries.size,
            "file_deleted" to deleteFile,
        )
    }

    fun verifyInstalledModel(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val modelId = payload["model_id"]?.toString()?.trim().orEmpty()
        val version = payload["version"]?.toString()?.trim().orEmpty()
        if (modelId.isBlank() || version.isBlank()) {
            return mapOf(
                "ok" to false,
                "message" to "model_id and version are required",
            )
        }

        val report = validationService.validateInstalledModel(modelId, version)
        val status = if (report.valid) "succeeded" else "failed"
        val now = System.currentTimeMillis()
        val installId = UUID.randomUUID().toString()
        repository.upsertInstallRun(
            AiInstallRunRecord(
                installId = installId,
                modelId = modelId,
                version = version,
                action = "verify",
                sourceUri = "",
                expectedHash = "",
                actualHash = "",
                status = status,
                details = report.toMap(),
                retryCount = 0,
                createdAtMs = now,
                startedAtMs = now,
                finishedAtMs = now,
                errorMessage = if (report.valid) "" else "Verification failed",
            ),
        )

        return mapOf(
            "ok" to report.valid,
            "install_id" to installId,
            "validation" to report.toMap(),
        )
    }

    fun detectModelUpdates(): List<Map<String, Any>> {
        ensureInitialized()
        val all = repository.listModels(installedOnly = null)
        val byModelId = all.groupBy { it.modelId }
        val updates = mutableListOf<Map<String, Any>>()

        byModelId.forEach { (modelId, versions) ->
            val installedVersions = versions.filter { it.installed }
            if (installedVersions.isEmpty()) {
                return@forEach
            }
            val availableVersions = versions
            if (availableVersions.isEmpty()) {
                return@forEach
            }
            val installedLatest = installedVersions.maxWithOrNull { a, b -> compareVersions(a.version, b.version) } ?: return@forEach
            val availableLatest = availableVersions.maxWithOrNull { a, b -> compareVersions(a.version, b.version) } ?: return@forEach
            if (compareVersions(availableLatest.version, installedLatest.version) > 0) {
                updates += mapOf(
                    "model_id" to modelId,
                    "installed_version" to installedLatest.version,
                    "latest_version" to availableLatest.version,
                    "installed" to installedLatest.toMap(),
                    "latest" to availableLatest.toMap(),
                )
            }
        }

        return updates.sortedBy { it["model_id"]?.toString() }
    }

    fun enqueueTask(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val taskType = payload["task_type"]?.toString()?.trim().orEmpty().ifBlank { "custom" }
        val modelId = payload["model_id"]?.toString()?.trim().orEmpty()
        val version = payload["version"]?.toString()?.trim().orEmpty()
        val runtimeHint = payload["runtime_hint"]?.toString()?.trim().orEmpty()
        val priority = (payload["priority"] as? Number)?.toInt() ?: 0
        val maxRetries = (payload["max_retries"] as? Number)?.toInt() ?: settingsManager.getSettings().maxQueueRetries
        val timeoutMs = (payload["timeout_ms"] as? Number)?.toLong() ?: settingsManager.getSettings().defaultTaskTimeoutMs
        val dependencyTaskIds = ((payload["dependency_task_ids"] as? List<*>)
            ?: (payload["depends_on"] as? List<*>))
            ?.mapNotNull { it?.toString()?.trim() }
            ?.filter { it.isNotBlank() }
            ?: emptyList()
        val taskPayload = (payload["payload"] as? Map<*, *>)?.toStringKeyMap() ?: payload

        val task = executionScheduler.enqueue(
            taskType = taskType,
            modelId = modelId,
            version = version,
            runtimeHint = runtimeHint,
            priority = priority,
            maxRetries = maxRetries,
            timeoutMs = timeoutMs,
            dependencyTaskIds = dependencyTaskIds,
            payload = taskPayload,
        )
        return task.toMap()
    }

    fun semanticSearch(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val rawCandidates = (payload["candidates"] as? List<*>)
            ?.mapNotNull { (it as? Map<*, *>)?.toStringKeyMap() }
            ?.filter { candidate -> candidate["image_id"]?.toIntOrNullValue() != null }
            ?: emptyList()
        if (rawCandidates.isEmpty()) {
            return mapOf(
                "ok" to true,
                "status" to "succeeded",
                "matches" to emptyList<Map<String, Any>>(),
                "result" to mapOf("matches" to emptyList<Map<String, Any>>()),
                "message" to "No candidates were provided for semantic ranking",
            )
        }

        val topKDefault = minOf(200, rawCandidates.size)
        val topK = payload["top_k"].toIntValue(defaultValue = topKDefault)
            .coerceIn(1, rawCandidates.size)
        val timeoutMs = payload["timeout_ms"].toLongValue(defaultValue = DEFAULT_SEMANTIC_TIMEOUT_MS)
            .coerceIn(1_000L, 60_000L)

        val model = bootstrapBuiltinSemanticModel()
        val taskPayload = linkedMapOf<String, Any>(
            "query" to payload["query"]?.toString().orEmpty(),
            "candidates" to rawCandidates,
            "top_k" to topK,
        )
        val queryEmbedding = (payload["query_embedding"] as? List<*>)
            ?.mapNotNull { it.toDoubleOrNullValue() }
            ?: emptyList()
        if (queryEmbedding.isNotEmpty()) {
            taskPayload["query_embedding"] = queryEmbedding
        }

        val task = executionScheduler.enqueue(
            taskType = "similarity_search",
            modelId = model.modelId,
            version = model.version,
            runtimeHint = BUILTIN_RUNTIME_ID,
            priority = 20,
            maxRetries = 0,
            timeoutMs = timeoutMs,
            payload = taskPayload,
        )

        val completedTask = awaitTaskTerminalState(task.taskId, timeoutMs + TASK_SETTLE_WINDOW_MS)
            ?: return mapOf(
                "ok" to false,
                "status" to "timeout",
                "task_id" to task.taskId,
                "matches" to emptyList<Map<String, Any>>(),
                "result" to mapOf("matches" to emptyList<Map<String, Any>>()),
                "message" to "Semantic search task timed out while waiting for completion",
            )

        val matches = extractSemanticMatches(completedTask.result).take(topK)
        val ok = completedTask.status == "succeeded"
        val fallbackMessage = if (ok) {
            "Semantic search completed"
        } else {
            completedTask.errorMessage.ifBlank { "Semantic search failed" }
        }
        val message = completedTask.result["message"]?.toString().orEmpty().ifBlank { fallbackMessage }

        return mapOf(
            "ok" to ok,
            "status" to completedTask.status,
            "task_id" to completedTask.taskId,
            "matches" to matches,
            "result" to mapOf("matches" to matches),
            "message" to message,
        )
    }

    fun runPipeline(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        if (payload["items"] is List<*>) {
            return runBatchPipeline(payload)
        }

        val normalizedTaskType = AiTaskTypes.normalize(
            payload["task_type"]?.toString()
                ?: payload["pipeline_type"]?.toString()
                ?: "",
        )
        if (normalizedTaskType.isBlank()) {
            return mapOf("ok" to false, "status" to "invalid", "message" to "task_type is required")
        }
        if (!AiTaskTypes.isExecutionTask(normalizedTaskType)) {
            return mapOf(
                "ok" to false,
                "status" to "unsupported",
                "message" to "task_type '$normalizedTaskType' is not supported by execution pipeline",
            )
        }

        val stages = resolvePipelineStages(normalizedTaskType, payload)
        if (stages.isEmpty()) {
            return mapOf(
                "ok" to false,
                "status" to "invalid",
                "message" to "No executable stages resolved for task_type '$normalizedTaskType'",
            )
        }

        val model = resolvePipelineModel(payload)
        val runtimeHint = payload["runtime_hint"]?.toString()?.trim().orEmpty()
            .ifBlank { model.requiredRuntime.ifBlank { BUILTIN_RUNTIME_ID } }
        val priority = payload["priority"].toIntValue(defaultValue = DEFAULT_PIPELINE_PRIORITY)
        val maxRetries = payload["max_retries"].toIntValue(defaultValue = 1).coerceAtLeast(0)
        val timeoutMs = payload["timeout_ms"].toLongValue(defaultValue = DEFAULT_PIPELINE_STAGE_TIMEOUT_MS)
            .coerceIn(1_000L, 180_000L)
        val pipelineId = payload["pipeline_id"]?.toString()?.trim().orEmpty().ifBlank { UUID.randomUUID().toString() }

        return executePipelineStages(
            pipelineId = pipelineId,
            pipelineType = normalizedTaskType,
            payload = payload,
            stages = stages,
            model = model,
            runtimeHint = runtimeHint,
            priority = priority,
            maxRetries = maxRetries,
            timeoutMs = timeoutMs,
        )
    }

    fun runBatchPipeline(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val rawItems = (payload["items"] as? List<*>)
            ?.mapNotNull { (it as? Map<*, *>)?.toStringKeyMap() }
            ?: emptyList()
        if (rawItems.isEmpty()) {
            return mapOf("ok" to false, "status" to "invalid", "message" to "items are required for batch execution")
        }
        if (rawItems.size > MAX_BATCH_ITEMS) {
            return mapOf(
                "ok" to false,
                "status" to "invalid",
                "message" to "batch size ${rawItems.size} exceeds max $MAX_BATCH_ITEMS",
            )
        }

        val shared = payload.toMutableMap().apply { remove("items") }
        val results = mutableListOf<Map<String, Any>>()
        rawItems.forEachIndexed { index, item ->
            val merged = linkedMapOf<String, Any>()
            merged.putAll(shared)
            merged.putAll(item)
            merged.remove("items")
            if (merged["task_type"] == null && merged["pipeline_type"] == null) {
                val fallbackTaskType = payload["task_type"]?.toString()?.trim().orEmpty()
                    .ifBlank { payload["pipeline_type"]?.toString()?.trim().orEmpty() }
                if (fallbackTaskType.isNotBlank()) {
                    merged["task_type"] = fallbackTaskType
                }
            }

            val itemResult = runPipeline(merged)
            results += mapOf(
                "index" to index,
                "ok" to (itemResult["ok"] as? Boolean ?: false),
                "result" to itemResult,
            )
        }

        val succeeded = results.count { it["ok"] == true }
        val failed = results.size - succeeded
        return mapOf(
            "ok" to (failed == 0),
            "status" to if (failed == 0) "succeeded" else "partial",
            "batch_size" to results.size,
            "succeeded" to succeeded,
            "failed" to failed,
            "items" to results,
        )
    }

    fun executeKnowledgePack(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val merged = linkedMapOf<String, Any>()
        merged.putAll(payload)
        merged["task_type"] = "knowledge_pack_execution"
        return runPipeline(merged)
    }

    fun runMultiStagePipeline(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val stages = (payload["stages"] as? List<*>)
            ?.mapNotNull { it?.toString()?.trim() }
            ?.filter { it.isNotBlank() }
            ?: emptyList()
        if (stages.isEmpty()) {
            return mapOf("ok" to false, "status" to "invalid", "message" to "stages are required for multi-stage pipeline")
        }
        val merged = linkedMapOf<String, Any>()
        merged.putAll(payload)
        if (merged["task_type"] == null && merged["pipeline_type"] == null) {
            merged["task_type"] = stages.last()
        }
        return runPipeline(merged)
    }

    fun cancelTask(taskId: String): Boolean {
        ensureInitialized()
        return executionScheduler.cancelTask(taskId)
    }

    fun pauseTask(taskId: String): Boolean {
        ensureInitialized()
        return executionScheduler.pauseTask(taskId)
    }

    fun resumeTask(taskId: String): Boolean {
        ensureInitialized()
        return executionScheduler.resumeTask(taskId)
    }

    fun retryTask(taskId: String): Boolean {
        ensureInitialized()
        return executionScheduler.retryTask(taskId)
    }

    fun listTasks(limit: Int = 200): List<Map<String, Any>> {
        ensureInitialized()
        return executionScheduler.listTasks(limit).map { it.toMap() }
    }

    fun resumeQueue() {
        ensureInitialized()
        executionScheduler.resume()
    }

    fun pauseQueue() {
        ensureInitialized()
        executionScheduler.pause()
    }

    fun listInstallRuns(limit: Int = 100): List<Map<String, Any>> {
        ensureInitialized()
        return repository.listInstallRuns(limit).map { it.toMap() }
    }

    fun listExecutionSessions(limit: Int = 200): List<Map<String, Any>> {
        ensureInitialized()
        return executionHistory.listSessions(limit).map { it.toMap() }
    }

    fun listExecutionEvents(sessionId: String, limit: Int = 500): List<Map<String, Any>> {
        ensureInitialized()
        return executionHistory.listEvents(sessionId, limit).map { it.toMap() }
    }

    fun listRuntimeHealthSnapshots(limit: Int = 200): List<Map<String, Any>> {
        ensureInitialized()
        return runtimeHealthMonitor.listSnapshots(limit).map { it.toMap() }
    }

    fun registerPlugin(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val now = System.currentTimeMillis()
        val pluginId = payload["plugin_id"]?.toString()?.trim().orEmpty()
        if (pluginId.isBlank()) {
            return mapOf("ok" to false, "message" to "plugin_id is required")
        }
        val plugin = AiPluginDescriptor(
            pluginId = pluginId,
            version = payload["version"]?.toString()?.trim().orEmpty().ifBlank { "1.0.0" },
            displayName = payload["display_name"]?.toString()?.trim().orEmpty().ifBlank { pluginId },
            enabled = payload["enabled"].toBooleanValue(defaultValue = true),
            capabilities = (payload["capabilities"] as? List<*>)?.mapNotNull { it?.toString() } ?: emptyList(),
            metadata = payload["metadata"].toStringMap(),
            registeredAtMs = (payload["registered_at_ms"] as? Number)?.toLong() ?: now,
            updatedAtMs = now,
        )
        repository.upsertPlugin(plugin)
        return mapOf("ok" to true, "plugin" to plugin.toMap())
    }

    fun listPlugins(enabledOnly: Boolean? = null): List<Map<String, Any>> {
        ensureInitialized()
        return repository.listPlugins(enabledOnly).map { it.toMap() }
    }

    fun registerCapability(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val now = System.currentTimeMillis()
        val capabilityId = payload["capability_id"]?.toString()?.trim().orEmpty()
        if (capabilityId.isBlank()) {
            return mapOf("ok" to false, "message" to "capability_id is required")
        }
        val capability = AiCapabilityDescriptor(
            capabilityId = capabilityId,
            providerId = payload["provider_id"]?.toString()?.trim().orEmpty().ifBlank { "local_ai_manager" },
            capabilityType = payload["capability_type"]?.toString()?.trim().orEmpty().ifBlank { "generic" },
            status = payload["status"]?.toString()?.trim().orEmpty().ifBlank { "available" },
            metadata = payload["metadata"].toStringMap(),
            registeredAtMs = (payload["registered_at_ms"] as? Number)?.toLong() ?: now,
            updatedAtMs = now,
        )
        repository.upsertCapability(capability)
        return mapOf("ok" to true, "capability" to capability.toMap())
    }

    fun listCapabilities(providerId: String = ""): List<Map<String, Any>> {
        ensureInitialized()
        return repository.listCapabilities(providerId.trim()).map { it.toMap() }
    }

    fun listCacheEntries(limit: Int = 200): List<Map<String, Any>> {
        ensureInitialized()
        return modelCache.listEntries(limit).map { it.toMap() }
    }

    fun upsertCacheEntry(payload: Map<String, Any>): Map<String, Any> {
        ensureInitialized()
        val modelId = payload["model_id"]?.toString()?.trim().orEmpty()
        val cacheKey = payload["cache_key"]?.toString()?.trim().orEmpty()
        val artifactPath = payload["artifact_path"]?.toString()?.trim().orEmpty()
        val sizeBytes = (payload["size_bytes"] as? Number)?.toLong() ?: File(artifactPath).length()
        if (modelId.isBlank() || cacheKey.isBlank() || artifactPath.isBlank()) {
            return mapOf("ok" to false, "message" to "model_id, cache_key, and artifact_path are required")
        }

        modelCache.upsertEntry(
            modelId = modelId,
            cacheKey = cacheKey,
            artifactPath = artifactPath,
            sizeBytes = sizeBytes,
            pinned = payload["pinned"].toBooleanValue(defaultValue = false),
            metadata = payload["metadata"].toStringMap(),
        )
        return mapOf("ok" to true, "cache_key" to cacheKey)
    }

    fun pruneCache(): Map<String, Any> {
        ensureInitialized()
        val budget = resourceManager.computeCacheBudgetBytes()
        return modelCache.pruneToBudget(budget)
    }

    fun validateInfrastructure(): Map<String, Any> {
        ensureInitialized()
        val infrastructure = validationService.validateInfrastructureSnapshot()
        val installedReports = repository.listModels(installedOnly = true).map {
            val report = validationService.validateInstalledModel(it.modelId, it.version)
            mapOf(
                "model_id" to it.modelId,
                "version" to it.version,
                "valid" to report.valid,
                "issues" to report.issues.map { issue ->
                    mapOf(
                        "code" to issue.code,
                        "message" to issue.message,
                        "severity" to issue.severity,
                    )
                },
            )
        }
        val sessions = repository.listExecutionSessions(limit = 200)
        val runtimeHealth = repository.listRuntimeHealthSnapshots(limit = 200)

        return mapOf(
            "ok" to (infrastructure.valid && installedReports.none { (it["valid"] as? Boolean) == false }),
            "infrastructure" to infrastructure.toMap(),
            "models" to installedReports,
            "execution_history" to mapOf(
                "total_sessions" to sessions.size,
                "failed_sessions" to sessions.count { it.status == "failed" },
                "paused_sessions" to sessions.count { it.status == "paused" },
                "retry_scheduled_sessions" to sessions.count { it.status == "retry_scheduled" },
            ),
            "runtime_health" to mapOf(
                "samples" to runtimeHealth.size,
                "unhealthy_samples" to runtimeHealth.count { !it.healthy },
            ),
            "supported_execution_task_types" to AiTaskTypes.EXECUTION_TASKS.sorted(),
        )
    }

    private fun bootstrapAssetCapabilities() {
        runCatching {
            val modelCapabilities = loadAssetJson("model_manager_capabilities.json")
            if (modelCapabilities != null) {
                val supports = modelCapabilities.optJSONArray("supports")
                if (supports != null) {
                    for (i in 0 until supports.length()) {
                        val capability = supports.optString(i, "").trim()
                        if (capability.isBlank()) {
                            continue
                        }
                        repository.upsertCapability(
                            AiCapabilityDescriptor(
                                capabilityId = "asset.support.$capability",
                                providerId = "asset:model_manager_capabilities",
                                capabilityType = "model_support",
                                status = "available",
                                metadata = mapOf("value" to capability),
                                registeredAtMs = System.currentTimeMillis(),
                                updatedAtMs = System.currentTimeMillis(),
                            ),
                        )
                    }
                }

                val operations = modelCapabilities.optJSONArray("operations")
                if (operations != null) {
                    for (i in 0 until operations.length()) {
                        val operation = operations.optString(i, "").trim()
                        if (operation.isBlank()) {
                            continue
                        }
                        repository.upsertCapability(
                            AiCapabilityDescriptor(
                                capabilityId = "asset.operation.$operation",
                                providerId = "asset:model_manager_capabilities",
                                capabilityType = "model_operation",
                                status = "available",
                                metadata = mapOf("value" to operation),
                                registeredAtMs = System.currentTimeMillis(),
                                updatedAtMs = System.currentTimeMillis(),
                            ),
                        )
                    }
                }
            }

            val storageSupport = loadAssetJson("storage_support.json")
            if (storageSupport != null) {
                val providers = storageSupport.optJSONArray("android_storage")
                if (providers != null) {
                    for (i in 0 until providers.length()) {
                        val provider = providers.optString(i, "").trim()
                        if (provider.isBlank()) {
                            continue
                        }
                        repository.upsertCapability(
                            AiCapabilityDescriptor(
                                capabilityId = "asset.storage.$provider",
                                providerId = "asset:storage_support",
                                capabilityType = "storage_provider",
                                status = "available",
                                metadata = mapOf("value" to provider),
                                registeredAtMs = System.currentTimeMillis(),
                                updatedAtMs = System.currentTimeMillis(),
                            ),
                        )
                    }
                }
            }
        }.onFailure {
            Log.w(TAG, "Failed to bootstrap AI capabilities from assets", it)
        }
    }

    private fun bootstrapBuiltinBackend() {
        val alreadyRegistered = backendManager.snapshotBackends().any {
            it.runtimeId.equals(BUILTIN_RUNTIME_ID, ignoreCase = true)
        }
        if (!alreadyRegistered) {
            backendManager.registerBackend(LocalHeuristicAiBackend(runtimeId = BUILTIN_RUNTIME_ID))
        }
    }

    private fun bootstrapBuiltinSemanticModel(): AiModelDescriptor {
        val now = System.currentTimeMillis()
        val existing = repository.getModel(BUILTIN_MODEL_ID, BUILTIN_MODEL_VERSION)
        val modelRoot = File(appContext.filesDir, "local_ai_models").apply { mkdirs() }
        val modelFile = File(modelRoot, "${BUILTIN_MODEL_ID}_${BUILTIN_MODEL_VERSION}.model")
        if (!modelFile.exists()) {
            modelFile.writeText("AILM local semantic model marker")
        }

        val descriptor = AiModelDescriptor(
            modelId = BUILTIN_MODEL_ID,
            version = BUILTIN_MODEL_VERSION,
            displayName = "Local Semantic Baseline",
            sizeBytes = modelFile.length(),
            hashSha256 = sha256Hex(modelFile),
            supportedTasks = AiTaskTypes.EXECUTION_TASKS.sorted(),
            requiredRuntime = BUILTIN_RUNTIME_ID,
            supportedRuntimes = listOf(BUILTIN_RUNTIME_ID, AiRuntimeType.CUSTOM.raw),
            dependencies = emptyList(),
            requiredHardware = emptyMap(),
            compatibility = mapOf("local_only" to true),
            metadata = mapOf(
                "builtin" to true,
                "provider" to "LocalHeuristicAiBackend",
            ),
            source = "builtin",
            sourceUri = "asset://local_heuristic_backend",
            installed = true,
            installState = "installed",
            installPath = modelFile.absolutePath,
            createdAtMs = existing?.createdAtMs ?: now,
            updatedAtMs = now,
        )
        repository.upsertModel(descriptor)
        return descriptor
    }

    private fun executePipelineStages(
        pipelineId: String,
        pipelineType: String,
        payload: Map<String, Any>,
        stages: List<String>,
        model: AiModelDescriptor,
        runtimeHint: String,
        priority: Int,
        maxRetries: Int,
        timeoutMs: Long,
    ): Map<String, Any> {
        val stageRecords = mutableListOf<Map<String, Any>>()
        val stageOutputs = linkedMapOf<String, Map<String, Any>>()
        val taskIds = mutableListOf<String>()
        var dependencyTaskId = ""

        stages.forEachIndexed { index, stageType ->
            val stagePayload = buildStagePayload(
                payload = payload,
                pipelineId = pipelineId,
                pipelineType = pipelineType,
                stageType = stageType,
                stageIndex = index + 1,
                stageTotal = stages.size,
                stageOutputs = stageOutputs,
            )
            val task = executionScheduler.enqueue(
                taskType = stageType,
                modelId = model.modelId,
                version = model.version,
                runtimeHint = runtimeHint,
                priority = priority,
                maxRetries = maxRetries,
                timeoutMs = timeoutMs,
                dependencyTaskIds = if (dependencyTaskId.isBlank()) emptyList() else listOf(dependencyTaskId),
                payload = stagePayload,
            )
            taskIds += task.taskId

            val completedTask = awaitTaskTerminalState(task.taskId, timeoutMs + TASK_SETTLE_WINDOW_MS)
            if (completedTask == null) {
                stageRecords += mapOf(
                    "stage_type" to stageType,
                    "task_id" to task.taskId,
                    "status" to "timeout",
                    "message" to "Stage timed out while waiting for completion",
                )
                return mapOf(
                    "ok" to false,
                    "status" to "timeout",
                    "pipeline_id" to pipelineId,
                    "pipeline_type" to pipelineType,
                    "task_ids" to taskIds,
                    "stages" to stageRecords,
                )
            }

            stageRecords += mapOf(
                "stage_type" to stageType,
                "task_id" to completedTask.taskId,
                "status" to completedTask.status,
                "message" to completedTask.result["message"]?.toString().orEmpty().ifBlank {
                    completedTask.errorMessage.ifBlank { completedTask.status }
                },
            )

            if (completedTask.status != "succeeded") {
                return mapOf(
                    "ok" to false,
                    "status" to completedTask.status,
                    "pipeline_id" to pipelineId,
                    "pipeline_type" to pipelineType,
                    "task_ids" to taskIds,
                    "stages" to stageRecords,
                    "result" to completedTask.result,
                    "message" to completedTask.errorMessage.ifBlank { "Pipeline stage '$stageType' failed" },
                )
            }

            stageOutputs[stageType] = completedTask.result
            dependencyTaskId = completedTask.taskId
        }

        val finalStage = stages.last()
        val finalStageOutput = stageOutputs[finalStage] ?: emptyMap()
        val cacheReceipt = persistPipelineOutputCache(
            pipelineId = pipelineId,
            pipelineType = pipelineType,
            model = model,
            payload = payload,
            stages = stageRecords,
            finalStageOutput = finalStageOutput,
        )

        return mapOf(
            "ok" to true,
            "status" to "succeeded",
            "pipeline_id" to pipelineId,
            "pipeline_type" to pipelineType,
            "task_ids" to taskIds,
            "stages" to stageRecords,
            "result" to (finalStageOutput["result"] ?: finalStageOutput),
            "raw_result" to finalStageOutput,
            "cache" to cacheReceipt,
        )
    }

    private fun resolvePipelineStages(taskType: String, payload: Map<String, Any>): List<String> {
        val explicit = (payload["stages"] as? List<*>)
            ?.mapNotNull { it?.toString()?.trim() }
            ?.filter { it.isNotBlank() }
            ?.map { AiTaskTypes.normalize(it) }
            ?.filter { AiTaskTypes.isExecutionTask(it) }
            ?.distinct()
            ?: emptyList()
        if (explicit.isNotEmpty()) {
            return explicit
        }

        val defaults = when (taskType) {
            "ocr" -> listOf("metadata_extraction", "ocr")
            "captioning" -> listOf("metadata_extraction", "ocr", "captioning")
            "character_recognition" -> listOf("metadata_extraction", "ocr", "character_recognition")
            "series_recognition" -> listOf("metadata_extraction", "ocr", "series_recognition")
            "artist_recognition" -> listOf("metadata_extraction", "ocr", "artist_recognition")
            "tag_prediction" -> listOf("metadata_extraction", "ocr", "tag_prediction")
            "metadata_extraction" -> listOf("metadata_extraction")
            "prompt_generation" -> {
                listOf(
                    "metadata_extraction",
                    "ocr",
                    "captioning",
                    "tag_prediction",
                    "character_recognition",
                    "series_recognition",
                    "artist_recognition",
                    "prompt_generation",
                )
            }
            "embedding_generation" -> listOf("metadata_extraction", "embedding_generation")
            "similarity_search" -> listOf("embedding_generation", "similarity_search")
            "duplicate_detection" -> listOf("metadata_extraction", "embedding_generation", "duplicate_detection")
            "classification" -> listOf("metadata_extraction", "tag_prediction", "classification")
            "detection" -> listOf("metadata_extraction", "detection")
            "face_feature_extraction" -> listOf("metadata_extraction", "detection", "face_feature_extraction")
            "knowledge_pack_execution" -> listOf("knowledge_pack_execution")
            else -> listOf(taskType)
        }

        return defaults
            .map { AiTaskTypes.normalize(it) }
            .filter { AiTaskTypes.isExecutionTask(it) }
            .distinct()
    }

    private fun buildStagePayload(
        payload: Map<String, Any>,
        pipelineId: String,
        pipelineType: String,
        stageType: String,
        stageIndex: Int,
        stageTotal: Int,
        stageOutputs: Map<String, Map<String, Any>>,
    ): Map<String, Any> {
        val stagePayload = linkedMapOf<String, Any>()
        val nestedPayload = (payload["payload"] as? Map<*, *>)?.toStringKeyMap() ?: emptyMap()

        stagePayload.putAll(payload)
        stagePayload.putAll(nestedPayload)
        stagePayload.remove("items")
        stagePayload.remove("stages")

        stagePayload["pipeline_id"] = pipelineId
        stagePayload["pipeline_type"] = pipelineType
        stagePayload["stage_type"] = stageType
        stagePayload["stage_index"] = stageIndex
        stagePayload["stage_total"] = stageTotal

        if (stageOutputs.isNotEmpty()) {
            stagePayload["upstream_results"] = stageOutputs
        }

        stageOutputs["metadata_extraction"]?.let { metadataStage ->
            val metadata = extractResultMap(metadataStage)["metadata"].toStringMap()
            if (metadata.isNotEmpty() && stagePayload["metadata"].toStringMap().isEmpty()) {
                stagePayload["metadata"] = metadata
            }
        }

        stageOutputs["tag_prediction"]?.let { tagStage ->
            val tags = extractResultMap(tagStage)["tags"] as? List<*>
            if (tags != null && tags.isNotEmpty() && stagePayload["tags"] !is List<*>) {
                stagePayload["tags"] = tags.mapNotNull { it?.toString() }
            }
        }

        stageOutputs["captioning"]?.let { captionStage ->
            val caption = extractResultMap(captionStage)["caption"]?.toString().orEmpty()
            if (caption.isNotBlank() && stagePayload["caption"]?.toString().orEmpty().isBlank()) {
                stagePayload["caption"] = caption
            }
        }

        stageOutputs["ocr"]?.let { ocrStage ->
            val text = extractResultMap(ocrStage)["text"]?.toString().orEmpty()
            if (text.isNotBlank() && stagePayload["ocr_text"]?.toString().orEmpty().isBlank()) {
                stagePayload["ocr_text"] = text
            }
        }

        stageOutputs["embedding_generation"]?.let { embeddingStage ->
            val embedding = embeddingStage["embedding"] as? List<*>
            if (embedding != null && embedding.isNotEmpty() && stagePayload["query_embedding"] !is List<*>) {
                stagePayload["query_embedding"] = embedding
            }
        }

        stagePayload["task_type"] = stageType
        return stagePayload
    }

    private fun resolvePipelineModel(payload: Map<String, Any>): AiModelDescriptor {
        val modelId = payload["model_id"]?.toString()?.trim().orEmpty()
        val version = payload["version"]?.toString()?.trim().orEmpty()
        if (modelId.isBlank()) {
            return bootstrapBuiltinSemanticModel()
        }

        val resolved = if (version.isBlank()) {
            repository.getModel(modelId)
        } else {
            repository.getModel(modelId, version)
        }
        if (resolved != null && resolved.installed) {
            return resolved
        }
        return bootstrapBuiltinSemanticModel()
    }

    private fun persistPipelineOutputCache(
        pipelineId: String,
        pipelineType: String,
        model: AiModelDescriptor,
        payload: Map<String, Any>,
        stages: List<Map<String, Any>>,
        finalStageOutput: Map<String, Any>,
    ): Map<String, Any> {
        val outputDir = File(appContext.filesDir, "local_ai_pipeline_outputs").apply { mkdirs() }
        val outputFile = File(outputDir, "${pipelineType}_${pipelineId}.json")
        val snapshot = linkedMapOf<String, Any>(
            "pipeline_id" to pipelineId,
            "pipeline_type" to pipelineType,
            "model_id" to model.modelId,
            "model_version" to model.version,
            "payload" to payload,
            "stages" to stages,
            "result" to finalStageOutput,
            "persisted_at_ms" to System.currentTimeMillis(),
        )
        outputFile.writeText(LocalAiJson.encodeMap(snapshot))

        val cacheType = when (pipelineType) {
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

        val baseCacheKey = "pipeline_output:${pipelineType}:$pipelineId"
        modelCache.upsertEntry(
            modelId = model.modelId,
            cacheKey = baseCacheKey,
            artifactPath = outputFile.absolutePath,
            sizeBytes = outputFile.length(),
            pinned = false,
            metadata = mapOf(
                "cache_type" to cacheType,
                "pipeline_id" to pipelineId,
                "pipeline_type" to pipelineType,
            ),
        )

        val imageId = payload["image_id"].toIntOrNullValue()
        if (imageId != null) {
            modelCache.upsertEntry(
                modelId = model.modelId,
                cacheKey = "pipeline_output_latest:${pipelineType}:image:$imageId",
                artifactPath = outputFile.absolutePath,
                sizeBytes = outputFile.length(),
                pinned = false,
                metadata = mapOf(
                    "cache_type" to "${cacheType}_latest",
                    "pipeline_type" to pipelineType,
                    "image_id" to imageId,
                ),
            )
        }

        return mapOf(
            "cache_key" to baseCacheKey,
            "artifact_path" to outputFile.absolutePath,
            "size_bytes" to outputFile.length(),
        )
    }

    private fun extractResultMap(stageOutput: Map<String, Any>): Map<String, Any> {
        return (stageOutput["result"] as? Map<*, *>)?.toStringKeyMap() ?: emptyMap()
    }

    private fun awaitTaskTerminalState(taskId: String, timeoutMs: Long): AiTaskRecord? {
        val deadlineAtMs = System.currentTimeMillis() + timeoutMs.coerceAtLeast(1_000L)
        var latest = repository.getTask(taskId)
        while (latest != null && latest.status !in TERMINAL_TASK_STATUSES && System.currentTimeMillis() < deadlineAtMs) {
            Thread.sleep(TASK_POLL_INTERVAL_MS)
            latest = repository.getTask(taskId)
        }
        return latest
    }

    private fun extractSemanticMatches(result: Map<String, Any>): List<Map<String, Any>> {
        val directMatches = (result["matches"] as? List<*>)
            ?.mapNotNull { (it as? Map<*, *>)?.toStringKeyMap() }
            ?: emptyList()
        if (directMatches.isNotEmpty()) {
            return directMatches
        }

        val nestedResult = (result["result"] as? Map<*, *>)?.toStringKeyMap() ?: return emptyList()
        return (nestedResult["matches"] as? List<*>)
            ?.mapNotNull { (it as? Map<*, *>)?.toStringKeyMap() }
            ?: emptyList()
    }

    private fun payloadToModelDescriptor(
        payload: Map<String, Any>,
        installed: Boolean,
        installState: String,
        installPath: String,
    ): AiModelDescriptor {
        val now = System.currentTimeMillis()
        val modelId = payload["model_id"]?.toString()?.trim().orEmpty()
        val version = payload["version"]?.toString()?.trim().orEmpty().ifBlank { "1.0.0" }
        val supportedTasks = (payload["supported_tasks"] as? List<*>)
            ?.mapNotNull { it?.toString()?.trim()?.takeIf { item -> item.isNotBlank() } }
            ?.map { AiTaskTypes.normalize(it) }
            ?: emptyList()
        val requiredRuntime = payload["required_runtime"]?.toString()?.trim().orEmpty()
        val supportedRuntimes = (payload["supported_runtimes"] as? List<*>)
            ?.mapNotNull { it?.toString()?.trim()?.lowercase()?.takeIf { runtime -> runtime.isNotBlank() } }
            ?: if (requiredRuntime.isNotBlank()) listOf(requiredRuntime.lowercase()) else emptyList()
        val dependencies = (payload["dependencies"] as? List<*>)
            ?.mapNotNull { it?.toString()?.trim()?.takeIf { dependency -> dependency.isNotBlank() } }
            ?: emptyList()

        return AiModelDescriptor(
            modelId = modelId,
            version = version,
            displayName = payload["display_name"]?.toString()?.trim().orEmpty().ifBlank { modelId },
            sizeBytes = (payload["size_bytes"] as? Number)?.toLong() ?: payload["size_bytes"]?.toString()?.toLongOrNull() ?: 0L,
            hashSha256 = payload["hash_sha256"]?.toString()?.trim().orEmpty().lowercase(),
            supportedTasks = supportedTasks,
            requiredRuntime = requiredRuntime,
            supportedRuntimes = supportedRuntimes,
            dependencies = dependencies,
            requiredHardware = payload["required_hardware"].toStringMap(),
            compatibility = payload["compatibility"].toStringMap(),
            metadata = payload["metadata"].toStringMap(),
            source = payload["source"]?.toString()?.trim().orEmpty().ifBlank { "manual" },
            sourceUri = payload["source_uri"]?.toString()?.trim().orEmpty(),
            installed = installed,
            installState = installState,
            installPath = installPath,
            createdAtMs = (payload["created_at_ms"] as? Number)?.toLong() ?: now,
            updatedAtMs = now,
        )
    }

    private fun compareVersions(a: String, b: String): Int {
        val aParts = normalizeVersion(a)
        val bParts = normalizeVersion(b)
        val max = maxOf(aParts.size, bParts.size)
        for (i in 0 until max) {
            val left = aParts.getOrElse(i) { 0 }
            val right = bParts.getOrElse(i) { 0 }
            if (left != right) {
                return left.compareTo(right)
            }
        }
        return a.compareTo(b)
    }

    private fun normalizeVersion(raw: String): List<Int> {
        return raw
            .trim()
            .removePrefix("v")
            .split('.')
            .map { segment -> segment.takeWhile { it.isDigit() } }
            .map { it.toIntOrNull() ?: 0 }
    }

    private fun loadAssetJson(assetName: String): JSONObject? {
        return runCatching {
            appContext.assets.open(assetName).bufferedReader().use { reader ->
                JSONObject(reader.readText())
            }
        }.getOrNull()
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

    private fun Any?.toStringMap(): Map<String, Any> {
        return when (this) {
            is Map<*, *> -> this.toStringKeyMap()
            else -> emptyMap()
        }
    }

    private fun Map<*, *>.toStringKeyMap(): Map<String, Any> {
        val result = linkedMapOf<String, Any>()
        this.forEach { (keyRaw, value) ->
            val key = keyRaw?.toString()?.trim().orEmpty()
            if (key.isBlank() || value == null) {
                return@forEach
            }
            result[key] = when (value) {
                is Map<*, *> -> value.toStringKeyMap()
                is List<*> -> value.mapNotNull { it }
                else -> value
            }
        }
        return result
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

    private fun Any?.toIntOrNullValue(): Int? {
        return when (this) {
            is Number -> this.toInt()
            else -> this?.toString()?.toIntOrNull()
        }
    }

    private fun Any?.toIntValue(defaultValue: Int): Int {
        return toIntOrNullValue() ?: defaultValue
    }

    private fun Any?.toLongValue(defaultValue: Long): Long {
        return when (this) {
            is Number -> this.toLong()
            else -> this?.toString()?.toLongOrNull() ?: defaultValue
        }
    }

    private fun Any?.toDoubleOrNullValue(): Double? {
        return when (this) {
            is Number -> this.toDouble()
            else -> this?.toString()?.toDoubleOrNull()
        }
    }

    private fun ensureInitialized() {
        check(initialized) { "LocalAiManager is not initialized" }
    }

    companion object {
        private const val TAG = "AilmLocalAiManager"
        private const val BUILTIN_RUNTIME_ID = "local_heuristic"
        private const val BUILTIN_MODEL_ID = "ailm_local_semantic"
        private const val BUILTIN_MODEL_VERSION = "1.0.0"
        private const val DEFAULT_SEMANTIC_TIMEOUT_MS = 7_500L
        private const val DEFAULT_PIPELINE_STAGE_TIMEOUT_MS = 12_000L
        private const val DEFAULT_PIPELINE_PRIORITY = 12
        private const val TASK_SETTLE_WINDOW_MS = 1_500L
        private const val TASK_POLL_INTERVAL_MS = 25L
        private const val MAX_BATCH_ITEMS = 500

        private val TERMINAL_TASK_STATUSES = setOf(
            "succeeded",
            "failed",
            "cancelled",
            "paused",
            "invalid",
            "unsupported",
            "resource_exhaustion",
        )
    }
}
