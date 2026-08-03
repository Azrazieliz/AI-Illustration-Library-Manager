package com.ailm.android.runtime.ai

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import android.os.StatFs

class LocalAiHardwareDetector(
    private val context: Context,
) {
    fun detectProfile(): AiHardwareProfile {
        val now = System.currentTimeMillis()
        val runtime = Runtime.getRuntime()
        val memoryInfo = ActivityManager.MemoryInfo()
        val activityManager = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        activityManager.getMemoryInfo(memoryInfo)

        val stats = StatFs(context.filesDir.absolutePath)
        val abiList = Build.SUPPORTED_ABIS?.toList() ?: emptyList()
        val simd = detectSimdFeatures(abiList)
        val pm = context.packageManager

        return AiHardwareProfile(
            cpuCores = runtime.availableProcessors().coerceAtLeast(1),
            gpuAvailable = pm.hasSystemFeature("android.hardware.opengles.aep") ||
                pm.hasSystemFeature("android.hardware.vulkan.level") ||
                pm.hasSystemFeature("android.hardware.vulkan.version"),
            npuAvailable = pm.hasSystemFeature("android.hardware.neuralnetworks") ||
                pm.hasSystemFeature("android.hardware.neuralnetworks.v1_3") ||
                pm.hasSystemFeature("android.hardware.ai.accelerator"),
            totalRamBytes = memoryInfo.totalMem,
            availableRamBytes = memoryInfo.availMem,
            totalStorageBytes = stats.totalBytes,
            availableStorageBytes = stats.availableBytes,
            threadCount = runtime.availableProcessors().coerceAtLeast(1),
            simdFeatures = simd,
            abiList = abiList,
            capturedAtMs = now,
        )
    }

    private fun detectSimdFeatures(abiList: List<String>): List<String> {
        val features = linkedSetOf<String>()
        val normalizedAbis = abiList.map { it.lowercase() }
        if (normalizedAbis.any { it.contains("arm64") || it.contains("armeabi") }) {
            features += "neon"
            features += "fp16"
        }
        if (normalizedAbis.any { it.contains("x86_64") || it == "x86" }) {
            features += "sse4"
            features += "avx"
        }
        if (normalizedAbis.any { it.contains("riscv") }) {
            features += "rvv"
        }
        return features.toList()
    }
}

class LocalAiResourceManager(
    private val hardwareProvider: () -> AiHardwareProfile,
    private val settingsProvider: () -> AiSettings,
) {
    fun validateHardwareRequirements(requiredHardware: Map<String, Any>): AiValidationReport {
        val profile = hardwareProvider()
        val issues = mutableListOf<AiValidationIssue>()

        val minRamBytes = requiredHardware["min_ram_bytes"].toLongValue(defaultValue = 0L)
        if (minRamBytes > 0L && profile.availableRamBytes < minRamBytes) {
            issues += AiValidationIssue(
                code = "ram_unavailable",
                message = "Available RAM ${profile.availableRamBytes} is below required $minRamBytes",
            )
        }

        val minStorageBytes = requiredHardware["min_storage_bytes"].toLongValue(defaultValue = 0L)
        if (minStorageBytes > 0L && profile.availableStorageBytes < minStorageBytes) {
            issues += AiValidationIssue(
                code = "storage_unavailable",
                message = "Available storage ${profile.availableStorageBytes} is below required $minStorageBytes",
            )
        }

        val requiresGpu = requiredHardware["requires_gpu"].toBooleanValue(defaultValue = false)
        if (requiresGpu && !profile.gpuAvailable) {
            issues += AiValidationIssue(
                code = "gpu_required",
                message = "Model requires GPU but GPU capability is not detected",
            )
        }

        val requiresNpu = requiredHardware["requires_npu"].toBooleanValue(defaultValue = false)
        if (requiresNpu && !profile.npuAvailable) {
            issues += AiValidationIssue(
                code = "npu_required",
                message = "Model requires NPU but NPU capability is not detected",
            )
        }

        val requiredSimd = (requiredHardware["required_simd"] as? List<*>)
            ?.mapNotNull { it?.toString()?.trim()?.lowercase() }
            ?.filter { it.isNotBlank() }
            ?: emptyList()
        requiredSimd.forEach { requirement ->
            if (profile.simdFeatures.none { it.equals(requirement, ignoreCase = true) }) {
                issues += AiValidationIssue(
                    code = "simd_missing",
                    message = "Required SIMD feature '$requirement' is not available",
                )
            }
        }

        return AiValidationReport(
            valid = issues.isEmpty(),
            issues = issues,
            metadata = mapOf(
                "hardware_profile" to profile.toMap(),
                "settings" to settingsProvider().toMap(),
            ),
        )
    }

    fun computeCacheBudgetBytes(): Long {
        val profile = hardwareProvider()
        val settings = settingsProvider()
        val safetyCap = (profile.availableStorageBytes * 0.75).toLong()
        return settings.maxCacheBytes.coerceAtMost(safetyCap).coerceAtLeast(64L * 1024L * 1024L)
    }

    private fun Any?.toLongValue(defaultValue: Long): Long {
        return when (this) {
            is Number -> this.toLong()
            else -> this?.toString()?.toLongOrNull() ?: defaultValue
        }
    }

    private fun Any?.toBooleanValue(defaultValue: Boolean): Boolean {
        return when (this) {
            is Boolean -> this
            is Number -> this.toInt() != 0
            else -> this?.toString()?.equals("true", ignoreCase = true) ?: defaultValue
        }
    }
}
