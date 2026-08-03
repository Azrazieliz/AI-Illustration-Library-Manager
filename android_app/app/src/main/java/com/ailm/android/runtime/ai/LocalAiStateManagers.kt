package com.ailm.android.runtime.ai

import java.io.File

class LocalAiSettingsManager(
    private val repository: LocalAiRepository,
) {
    fun getSettings(): AiSettings {
        val all = repository.listSettings()
        val maxCacheBytes = all[KEY_MAX_CACHE_BYTES]?.toLongOrNull() ?: DEFAULT.maxCacheBytes
        val maxQueueRetries = all[KEY_MAX_QUEUE_RETRIES]?.toIntOrNull() ?: DEFAULT.maxQueueRetries
        val maxConcurrentTasks = all[KEY_MAX_CONCURRENT_TASKS]?.toIntOrNull() ?: DEFAULT.maxConcurrentTasks
        val autoUpdateModels = all[KEY_AUTO_UPDATE_MODELS]?.toBooleanStrictOrNull() ?: DEFAULT.autoUpdateModels
        val allowCellular = all[KEY_ALLOW_CELLULAR]?.toBooleanStrictOrNull() ?: DEFAULT.allowCellularDownloads
        val preferredRuntimeOrder = LocalAiJson.decodeList(all[KEY_PREFERRED_RUNTIME_ORDER] ?: "[]")
            .map { it.toString() }
        val defaultTaskTimeoutMs = all[KEY_DEFAULT_TASK_TIMEOUT_MS]?.toLongOrNull() ?: DEFAULT.defaultTaskTimeoutMs
        val maxReservedRamBytes = all[KEY_MAX_RESERVED_RAM_BYTES]?.toLongOrNull() ?: DEFAULT.maxReservedRamBytes
        val schedulerPollIntervalMs = all[KEY_SCHEDULER_POLL_INTERVAL_MS]?.toLongOrNull() ?: DEFAULT.schedulerPollIntervalMs
        val schedulerIdleDelayMs = all[KEY_SCHEDULER_IDLE_DELAY_MS]?.toLongOrNull() ?: DEFAULT.schedulerIdleDelayMs

        val knownKeys = setOf(
            KEY_MAX_CACHE_BYTES,
            KEY_MAX_QUEUE_RETRIES,
            KEY_MAX_CONCURRENT_TASKS,
            KEY_AUTO_UPDATE_MODELS,
            KEY_ALLOW_CELLULAR,
            KEY_PREFERRED_RUNTIME_ORDER,
            KEY_DEFAULT_TASK_TIMEOUT_MS,
            KEY_MAX_RESERVED_RAM_BYTES,
            KEY_SCHEDULER_POLL_INTERVAL_MS,
            KEY_SCHEDULER_IDLE_DELAY_MS,
        )
        val extra = all
            .filterKeys { !knownKeys.contains(it) }
            .mapValues { it.value }

        return AiSettings(
            maxCacheBytes = maxCacheBytes,
            maxQueueRetries = maxQueueRetries,
            maxConcurrentTasks = maxConcurrentTasks,
            autoUpdateModels = autoUpdateModels,
            allowCellularDownloads = allowCellular,
            preferredRuntimeOrder = preferredRuntimeOrder,
            defaultTaskTimeoutMs = defaultTaskTimeoutMs.coerceAtLeast(1_000L),
            maxReservedRamBytes = maxReservedRamBytes.coerceAtLeast(0L),
            schedulerPollIntervalMs = schedulerPollIntervalMs.coerceAtLeast(50L),
            schedulerIdleDelayMs = schedulerIdleDelayMs.coerceAtLeast(100L),
            extra = extra,
        )
    }

    fun updateSettings(payload: Map<String, Any>): AiSettings {
        val current = getSettings()
        val merged = current.copy(
            maxCacheBytes = payload["max_cache_bytes"].toLongOrNull() ?: current.maxCacheBytes,
            maxQueueRetries = payload["max_queue_retries"].toIntOrNull() ?: current.maxQueueRetries,
            maxConcurrentTasks = payload["max_concurrent_tasks"].toIntOrNull() ?: current.maxConcurrentTasks,
            autoUpdateModels = payload["auto_update_models"].toBooleanOrNull() ?: current.autoUpdateModels,
            allowCellularDownloads = payload["allow_cellular_downloads"].toBooleanOrNull() ?: current.allowCellularDownloads,
            preferredRuntimeOrder = (payload["preferred_runtime_order"] as? List<*>)
                ?.mapNotNull { it?.toString() }
                ?: current.preferredRuntimeOrder,
            defaultTaskTimeoutMs = payload["default_task_timeout_ms"].toLongOrNull() ?: current.defaultTaskTimeoutMs,
            maxReservedRamBytes = payload["max_reserved_ram_bytes"].toLongOrNull() ?: current.maxReservedRamBytes,
            schedulerPollIntervalMs = payload["scheduler_poll_interval_ms"].toLongOrNull() ?: current.schedulerPollIntervalMs,
            schedulerIdleDelayMs = payload["scheduler_idle_delay_ms"].toLongOrNull() ?: current.schedulerIdleDelayMs,
            extra = current.extra + payload.filterKeys {
                it !in setOf(
                    "max_cache_bytes",
                    "max_queue_retries",
                    "max_concurrent_tasks",
                    "auto_update_models",
                    "allow_cellular_downloads",
                    "preferred_runtime_order",
                    "default_task_timeout_ms",
                    "max_reserved_ram_bytes",
                    "scheduler_poll_interval_ms",
                    "scheduler_idle_delay_ms",
                )
            },
        )

        repository.setSetting(KEY_MAX_CACHE_BYTES, merged.maxCacheBytes.toString())
        repository.setSetting(KEY_MAX_QUEUE_RETRIES, merged.maxQueueRetries.toString())
        repository.setSetting(KEY_MAX_CONCURRENT_TASKS, merged.maxConcurrentTasks.toString())
        repository.setSetting(KEY_AUTO_UPDATE_MODELS, merged.autoUpdateModels.toString())
        repository.setSetting(KEY_ALLOW_CELLULAR, merged.allowCellularDownloads.toString())
        repository.setSetting(KEY_PREFERRED_RUNTIME_ORDER, LocalAiJson.encodeList(merged.preferredRuntimeOrder))
        repository.setSetting(KEY_DEFAULT_TASK_TIMEOUT_MS, merged.defaultTaskTimeoutMs.toString())
        repository.setSetting(KEY_MAX_RESERVED_RAM_BYTES, merged.maxReservedRamBytes.toString())
        repository.setSetting(KEY_SCHEDULER_POLL_INTERVAL_MS, merged.schedulerPollIntervalMs.toString())
        repository.setSetting(KEY_SCHEDULER_IDLE_DELAY_MS, merged.schedulerIdleDelayMs.toString())
        merged.extra.forEach { (key, value) ->
            repository.setSetting(key, value.toString())
        }

        return merged
    }

    private fun Any?.toLongOrNull(): Long? {
        return when (this) {
            is Number -> this.toLong()
            else -> this?.toString()?.toLongOrNull()
        }
    }

    private fun Any?.toIntOrNull(): Int? {
        return when (this) {
            is Number -> this.toInt()
            else -> this?.toString()?.toIntOrNull()
        }
    }

    private fun Any?.toBooleanOrNull(): Boolean? {
        return when (this) {
            is Boolean -> this
            is Number -> this.toInt() != 0
            else -> this?.toString()?.lowercase()?.let {
                when (it) {
                    "true", "1", "yes", "on" -> true
                    "false", "0", "no", "off" -> false
                    else -> null
                }
            }
        }
    }

    companion object {
        private val DEFAULT = AiSettings()
        private const val KEY_MAX_CACHE_BYTES = "ai.max_cache_bytes"
        private const val KEY_MAX_QUEUE_RETRIES = "ai.max_queue_retries"
        private const val KEY_MAX_CONCURRENT_TASKS = "ai.max_concurrent_tasks"
        private const val KEY_AUTO_UPDATE_MODELS = "ai.auto_update_models"
        private const val KEY_ALLOW_CELLULAR = "ai.allow_cellular_downloads"
        private const val KEY_PREFERRED_RUNTIME_ORDER = "ai.preferred_runtime_order"
        private const val KEY_DEFAULT_TASK_TIMEOUT_MS = "ai.default_task_timeout_ms"
        private const val KEY_MAX_RESERVED_RAM_BYTES = "ai.max_reserved_ram_bytes"
        private const val KEY_SCHEDULER_POLL_INTERVAL_MS = "ai.scheduler_poll_interval_ms"
        private const val KEY_SCHEDULER_IDLE_DELAY_MS = "ai.scheduler_idle_delay_ms"
    }
}

class LocalAiModelCache(
    private val repository: LocalAiRepository,
) {
    fun upsertEntry(
        modelId: String,
        cacheKey: String,
        artifactPath: String,
        sizeBytes: Long,
        pinned: Boolean = false,
        metadata: Map<String, Any> = emptyMap(),
    ) {
        val now = System.currentTimeMillis()
        repository.upsertCacheEntry(
            AiCacheEntry(
                cacheKey = cacheKey,
                modelId = modelId,
                artifactPath = artifactPath,
                sizeBytes = sizeBytes,
                pinned = pinned,
                metadata = metadata,
                createdAtMs = now,
                lastAccessMs = now,
            ),
        )
    }

    fun touch(cacheKey: String): Boolean {
        return repository.touchCacheEntry(cacheKey)
    }

    fun getEntry(cacheKey: String): AiCacheEntry? {
        return repository.getCacheEntry(cacheKey)
    }

    fun removeEntry(cacheKey: String): Boolean {
        return repository.removeCacheEntry(cacheKey)
    }

    fun listEntries(limit: Int = 200): List<AiCacheEntry> {
        return repository.listCacheEntries(limit)
    }

    fun totalBytes(): Long {
        return repository.totalCacheBytes()
    }

    fun pruneToBudget(maxBytes: Long): Map<String, Any> {
        var currentBytes = repository.totalCacheBytes()
        var removedEntries = 0
        var removedBytes = 0L
        val removedKeys = mutableListOf<String>()

        if (currentBytes > maxBytes) {
            val evictionCandidates = repository.listEvictableCacheEntries()
            for (entry in evictionCandidates) {
                if (currentBytes <= maxBytes) {
                    break
                }
                val file = File(entry.artifactPath)
                if (file.exists()) {
                    file.delete()
                }
                repository.removeCacheEntry(entry.cacheKey)
                currentBytes -= entry.sizeBytes
                removedBytes += entry.sizeBytes
                removedEntries += 1
                removedKeys += entry.cacheKey
            }
        }

        return mapOf(
            "max_bytes" to maxBytes,
            "current_bytes" to currentBytes,
            "removed_entries" to removedEntries,
            "removed_bytes" to removedBytes,
            "removed_keys" to removedKeys,
        )
    }
}
