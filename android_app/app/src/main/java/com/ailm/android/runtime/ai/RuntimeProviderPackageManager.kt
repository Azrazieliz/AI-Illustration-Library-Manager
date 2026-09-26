package com.ailm.android.runtime.ai

import android.content.Context
import android.os.Build
import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest
import java.util.zip.ZipFile
import org.json.JSONObject

data class RuntimeProviderPackageManifest(
    val providerId: String,
    val displayName: String,
    val runtimeType: AiRuntimeType,
    val version: String,
    val libraryName: String,
    val nativeLibraries: Map<String, String>,
    val supportedAbis: Set<String>,
    val minimumAndroidApi: Int,
    val runtimeVersion: String,
    val supportedFormats: Set<String>,
    val supportedTasks: Set<String>,
    val supportedPrecisions: Set<String>,
    val supportedDelegates: Set<String>,
    val supportedDevices: Set<String>,
    val supportedTensorLayouts: Set<String>,
    val supportedQuantizations: Set<String>,
    val capabilities: Map<String, Any>,
    val providerSignature: String,
    val payloadDigests: Map<String, String>,
) {
    fun toCapabilities(abiCompatible: Boolean, apiCompatible: Boolean): AiRuntimeProviderCapabilities =
        AiRuntimeProviderCapabilities(
            providerId = providerId,
            backendName = displayName,
            runtimeType = runtimeType,
            supportedFormats = supportedFormats,
            supportedTasks = supportedTasks,
            supportedPrecisions = supportedPrecisions,
            supportedDevices = supportedDevices,
            supportedDelegates = supportedDelegates,
            supportedQuantizations = supportedQuantizations,
            supportedTensorLayouts = supportedTensorLayouts,
            supportedInputTypes = stringSet("supported_input_types"),
            supportedOutputTypes = stringSet("supported_output_types"),
            maximumContext = capabilities["maximum_context"]?.toString()?.toIntOrNull() ?: 0,
            maximumImageResolution = capabilities["maximum_image_resolution"]?.toString()?.toIntOrNull() ?: 0,
            runtimeVersion = runtimeVersion,
            abiCompatible = abiCompatible,
            androidApiCompatible = apiCompatible,
            metadata = capabilities + mapOf(
                "provider_package" to true,
                "provider_signature" to providerSignature,
                "minimum_android_api" to minimumAndroidApi,
                "supported_abis" to supportedAbis.sorted(),
            ),
        )

    private fun stringSet(key: String): Set<String> = (capabilities[key] as? List<*>)
        ?.mapNotNull { it?.toString()?.trim()?.lowercase()?.takeIf(String::isNotBlank) }
        ?.toSet()
        ?: emptySet()
}

data class RuntimeProviderPackageResult(
    val ok: Boolean,
    val message: String,
    val providerId: String = "",
    val state: AiRuntimeProviderState? = null,
) {
    fun toMap(): Map<String, Any> = mapOf(
        "ok" to ok,
        "message" to message,
        "provider_id" to providerId,
        "state" to (state?.name?.lowercase() ?: ""),
    )
}

/**
 * Loads self-contained provider archives. A package has runtime-provider.json at its root and
 * native libraries implementing PackagedNativeRuntimePlugin's JNI ABI.
 */
class RuntimeProviderPackageManager(
    context: Context,
    private val repository: LocalAiRepository,
    private val backendManager: LocalAiBackendManager,
    private val modelResolver: (String, String) -> AiModelDescriptor?,
) {
    private val root = File(context.filesDir, "runtime_providers").apply { mkdirs() }

    fun discover(): List<RuntimeProviderPackageResult> = root.listFiles()
        ?.filter { it.isDirectory }
        ?.sortedBy { it.name }
        ?.map { directory ->
            val manifest = readManifest(File(directory, MANIFEST_NAME))
                ?: return@map RuntimeProviderPackageResult(false, "Invalid provider manifest", directory.name)
            activate(manifest, directory, readEnabled(directory))
        }
        ?: emptyList()

    fun install(packageFile: File): RuntimeProviderPackageResult {
        if (!packageFile.isFile) return RuntimeProviderPackageResult(false, "Provider package was not found")
        return runCatching {
            ZipFile(packageFile).use { archive ->
                val entry = archive.getEntry(MANIFEST_NAME) ?: error("Provider package is missing $MANIFEST_NAME")
                val manifest = parseManifest(entry.let { archive.getInputStream(it).bufferedReader().use { reader -> reader.readText() } })
                validateArchive(archive, manifest)
                val destination = File(root, manifest.providerId)
                val staging = File(root, ".${manifest.providerId}.staging").apply { deleteRecursively(); mkdirs() }
                archive.entries().asSequence().forEach { zipEntry ->
                    if (zipEntry.isDirectory) return@forEach
                    val target = File(staging, zipEntry.name)
                    require(target.canonicalPath.startsWith(staging.canonicalPath + File.separator)) { "Invalid archive path" }
                    target.parentFile?.mkdirs()
                    archive.getInputStream(zipEntry).use { input -> target.outputStream().use(input::copyTo) }
                }
                destination.deleteRecursively()
                require(staging.renameTo(destination)) { "Unable to install provider package" }
                activate(manifest, destination, enabled = true)
            }
        }.getOrElse { error ->
            RuntimeProviderPackageResult(false, error.message ?: error.javaClass.simpleName)
        }
    }

    fun update(packageFile: File): RuntimeProviderPackageResult = install(packageFile)

    fun remove(providerId: String): RuntimeProviderPackageResult {
        val directory = providerDirectory(providerId) ?: return RuntimeProviderPackageResult(false, "Provider package was not found", providerId)
        val manifest = readManifest(File(directory, MANIFEST_NAME))
        if (manifest != null) {
            backendManager.unregisterBackend(manifest.providerId)
            NativeRuntimePluginRegistry.unregister(manifest.runtimeType)
        }
        return if (directory.deleteRecursively()) {
            repository.upsertPlugin(descriptor(providerId, "", providerId, false, emptySet(), mapOf("removed" to true)))
            RuntimeProviderPackageResult(true, "Provider package removed", providerId)
        } else {
            RuntimeProviderPackageResult(false, "Unable to remove provider package", providerId)
        }
    }

    fun setEnabled(providerId: String, enabled: Boolean): RuntimeProviderPackageResult {
        val directory = providerDirectory(providerId) ?: return RuntimeProviderPackageResult(false, "Provider package was not found", providerId)
        val manifest = readManifest(File(directory, MANIFEST_NAME)) ?: return RuntimeProviderPackageResult(false, "Invalid provider manifest", providerId)
        File(directory, STATE_NAME).writeText(JSONObject(mapOf("enabled" to enabled)).toString())
        return if (enabled) activate(manifest, directory, true) else {
            backendManager.unregisterBackend(manifest.providerId)
            NativeRuntimePluginRegistry.unregister(manifest.runtimeType)
            repository.upsertPlugin(descriptor(manifest.providerId, manifest.version, manifest.displayName, false, manifest.supportedTasks, manifest.capabilities))
            RuntimeProviderPackageResult(true, "Provider disabled", manifest.providerId, AiRuntimeProviderState.UNAVAILABLE)
        }
    }

    suspend fun probe(providerId: String): RuntimeProviderPackageResult {
        val provider = backendManager.snapshotProviders().firstOrNull { it.runtimeId == providerId }
            ?: return RuntimeProviderPackageResult(false, "Provider is not active", providerId)
        val health = provider.health()
        return RuntimeProviderPackageResult(health.state == AiRuntimeProviderState.AVAILABLE, health.message, providerId, health.state)
    }

    suspend fun benchmark(providerId: String, model: AiModelDescriptor): Map<String, Any> {
        val provider = backendManager.snapshotProviders().firstOrNull { it.runtimeId == providerId }
            ?: return mapOf("status" to "unavailable", "provider_id" to providerId)
        return provider.benchmark(model)
    }

    fun health(): List<Map<String, Any>> = backendManager.snapshotProviders().map { provider ->
        val capability = provider.queryCapabilities()
        mapOf(
            "provider_id" to provider.runtimeId,
            "state" to provider.providerState.name.lowercase(),
            "runtime_version" to capability.runtimeVersion,
            "abi_compatible" to capability.abiCompatible,
            "android_api_compatible" to capability.androidApiCompatible,
        )
    }

    private fun activate(
        manifest: RuntimeProviderPackageManifest,
        directory: File,
        enabled: Boolean,
    ): RuntimeProviderPackageResult {
        backendManager.unregisterBackend(manifest.providerId)
        NativeRuntimePluginRegistry.unregister(manifest.runtimeType)
        if (!enabled) {
            repository.upsertPlugin(descriptor(manifest.providerId, manifest.version, manifest.displayName, false, manifest.supportedTasks, manifest.capabilities))
            return RuntimeProviderPackageResult(true, "Provider disabled", manifest.providerId, AiRuntimeProviderState.UNAVAILABLE)
        }
        val libraryPath = manifest.nativeLibraries.entries.firstOrNull { (abi, _) ->
            Build.SUPPORTED_ABIS.any { supported -> supported.equals(abi, ignoreCase = true) }
        }?.value ?: return RuntimeProviderPackageResult(
            false,
            "Provider does not contain a native library for ${Build.SUPPORTED_ABIS.joinToString()}",
            manifest.providerId,
            AiRuntimeProviderState.UNAVAILABLE,
        )
        val library = File(directory, libraryPath)
        if (!library.isFile) {
            return RuntimeProviderPackageResult(false, "Provider native library is missing: $libraryPath", manifest.providerId, AiRuntimeProviderState.FAILED)
        }
        return runCatching {
            NativeRuntimePluginRegistry.register(PackagedNativeRuntimePlugin(manifest, library))
            val provider = OptionalNativeRuntimeProvider(
                runtimeType = manifest.runtimeType,
                libraryName = manifest.libraryName,
                modelResolver = modelResolver,
                providerId = manifest.providerId,
                nativeLibraryPath = library.absolutePath,
                declaredCapabilities = manifest.toCapabilities(
                    abiCompatible = true,
                    apiCompatible = Build.VERSION.SDK_INT >= manifest.minimumAndroidApi,
                ),
            )
            backendManager.registerBackend(provider)
            val active = provider.providerState == AiRuntimeProviderState.AVAILABLE
            repository.upsertPlugin(
                descriptor(
                    manifest.providerId,
                    manifest.version,
                    manifest.displayName,
                    active,
                    manifest.supportedTasks,
                    manifest.capabilities + mapOf("provider_state" to provider.providerState.name.lowercase()),
                ),
            )
            RuntimeProviderPackageResult(
                active,
                "Provider activation state: ${provider.providerState.name.lowercase()}",
                manifest.providerId,
                provider.providerState,
            )
        }.getOrElse { error ->
            NativeRuntimePluginRegistry.unregister(manifest.runtimeType)
            repository.upsertPlugin(descriptor(manifest.providerId, manifest.version, manifest.displayName, false, manifest.supportedTasks, manifest.capabilities))
            RuntimeProviderPackageResult(false, error.message ?: error.javaClass.simpleName, manifest.providerId, AiRuntimeProviderState.FAILED)
        }
    }

    private fun validateArchive(archive: ZipFile, manifest: RuntimeProviderPackageManifest) {
        require(manifest.providerId.matches(Regex("[a-z0-9_.-]+"))) { "provider_id contains unsupported characters" }
        require(manifest.version.isNotBlank()) { "version is required" }
        require(manifest.libraryName.isNotBlank()) { "library_name is required" }
        require(manifest.nativeLibraries.isNotEmpty()) { "native_libraries is required" }
        require(manifest.supportedAbis.isNotEmpty()) { "supported_abis is required" }
        require(manifest.providerSignature.equals(signatureFor(manifest), ignoreCase = true)) { "Provider signature validation failed" }
        manifest.nativeLibraries.values.forEach { path ->
            val entry = archive.getEntry(path) ?: error("Missing native library: $path")
            val expected = manifest.payloadDigests[path] ?: error("Native library digest missing: $path")
            val actual = archive.getInputStream(entry).use(::sha256)
            require(expected.equals(actual, ignoreCase = true)) { "Native library digest mismatch: $path" }
        }
    }

    private fun readManifest(file: File): RuntimeProviderPackageManifest? = runCatching { parseManifest(file.readText()) }.getOrNull()

    private fun parseManifest(raw: String): RuntimeProviderPackageManifest {
        val objectValue = JSONObject(raw)
        fun stringSet(key: String) = objectValue.optJSONArray(key)?.let { values ->
            (0 until values.length()).mapNotNull { values.optString(it).trim().lowercase().takeIf(String::isNotBlank) }.toSet()
        } ?: emptySet()
        val libraries = objectValue.optJSONObject("native_libraries")?.let { values ->
            values.keys().asSequence().associateWith { abi -> values.optString(abi).trim() }.filterValues(String::isNotBlank)
        } ?: emptyMap()
        val digests = objectValue.optJSONObject("payload_digests")?.let { values ->
            values.keys().asSequence().associateWith { path -> values.optString(path).trim() }.filterValues(String::isNotBlank)
        } ?: emptyMap()
        return RuntimeProviderPackageManifest(
            providerId = objectValue.optString("provider_id").trim(),
            displayName = objectValue.optString("display_name").trim().ifBlank { objectValue.optString("provider_id").trim() },
            runtimeType = AiRuntimeType.fromRaw(objectValue.optString("runtime_type")),
            version = objectValue.optString("version").trim(),
            libraryName = objectValue.optString("library_name").trim(),
            nativeLibraries = libraries,
            supportedAbis = stringSet("supported_abis"),
            minimumAndroidApi = objectValue.optInt("minimum_android_api", 30),
            runtimeVersion = objectValue.optString("runtime_version").trim().ifBlank { "unknown" },
            supportedFormats = stringSet("supported_model_formats"),
            supportedTasks = stringSet("supported_tasks"),
            supportedPrecisions = stringSet("supported_precisions"),
            supportedDelegates = stringSet("supported_delegates"),
            supportedDevices = stringSet("supported_devices"),
            supportedTensorLayouts = stringSet("supported_tensor_layouts"),
            supportedQuantizations = stringSet("supported_quantizations"),
            capabilities = LocalAiJson.fromJsonValue(objectValue.optJSONObject("provider_capabilities")) as? Map<String, Any> ?: emptyMap(),
            providerSignature = objectValue.optString("provider_signature").trim(),
            payloadDigests = digests,
        )
    }

    private fun signatureFor(manifest: RuntimeProviderPackageManifest): String = sha256(
        LocalAiJson.encodeMap(
            mapOf(
                "provider_id" to manifest.providerId,
                "runtime_type" to manifest.runtimeType.raw,
                "version" to manifest.version,
                "library_name" to manifest.libraryName,
                "native_libraries" to manifest.nativeLibraries.toSortedMap(),
                "supported_abis" to manifest.supportedAbis.sorted(),
                "minimum_android_api" to manifest.minimumAndroidApi,
                "runtime_version" to manifest.runtimeVersion,
                "supported_model_formats" to manifest.supportedFormats.sorted(),
                "supported_tasks" to manifest.supportedTasks.sorted(),
                "supported_precisions" to manifest.supportedPrecisions.sorted(),
                "supported_delegates" to manifest.supportedDelegates.sorted(),
                "supported_devices" to manifest.supportedDevices.sorted(),
                "supported_tensor_layouts" to manifest.supportedTensorLayouts.sorted(),
                "supported_quantizations" to manifest.supportedQuantizations.sorted(),
                "provider_capabilities" to manifest.capabilities.toSortedMap(),
                "payload_digests" to manifest.payloadDigests.toSortedMap(),
            ),
        ).toByteArray(),
    )

    private fun readEnabled(directory: File): Boolean = runCatching {
        JSONObject(File(directory, STATE_NAME).readText()).optBoolean("enabled", true)
    }.getOrDefault(true)

    private fun providerDirectory(providerId: String): File? = File(root, providerId.trim()).takeIf { it.isDirectory }

    private fun descriptor(
        providerId: String,
        version: String,
        displayName: String,
        enabled: Boolean,
        capabilities: Set<String>,
        metadata: Map<String, Any>,
    ) = AiPluginDescriptor(providerId, version, displayName, enabled, capabilities.sorted(), metadata, System.currentTimeMillis(), System.currentTimeMillis())

    private fun sha256(input: java.io.InputStream): String = input.use { stream ->
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        while (true) {
            val count = stream.read(buffer)
            if (count <= 0) break
            digest.update(buffer, 0, count)
        }
        digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes)
        .joinToString("") { "%02x".format(it) }

    private companion object {
        const val MANIFEST_NAME = "runtime-provider.json"
        const val STATE_NAME = "provider-state.json"
    }
}

private class PackagedNativeRuntimePlugin(
    private val manifest: RuntimeProviderPackageManifest,
    library: File,
) : NativeRuntimePlugin {
    override val runtimeType: AiRuntimeType = manifest.runtimeType
    override val libraryName: String = manifest.libraryName

    init {
        System.load(library.absolutePath)
    }

    override fun probe(): AiRuntimeProviderHealth = runCatching {
        val raw = LocalAiJson.decodeMap(nativeProbe(manifest.providerId))
        AiRuntimeProviderHealth(
            state = raw["state"]?.toString()?.let { value -> AiRuntimeProviderState.entries.firstOrNull { it.name.equals(value, true) } } ?: AiRuntimeProviderState.FAILED,
            message = raw["message"]?.toString().orEmpty().ifBlank { "Provider probe did not return a message" },
            memoryBytes = (raw["memory_bytes"] as? Number)?.toLong() ?: 0L,
            metadata = raw["metadata"] as? Map<String, Any> ?: emptyMap(),
        )
    }.getOrElse { error -> AiRuntimeProviderHealth(AiRuntimeProviderState.FAILED, error.message ?: error.javaClass.simpleName, 0L) }

    override fun queryCapabilities(): AiRuntimeProviderCapabilities = manifest.toCapabilities(true, true)

    override suspend fun loadModel(model: AiModelDescriptor): AiRuntimeModelHandle? {
        val raw = LocalAiJson.decodeMap(nativeLoadModel(LocalAiJson.encodeMap(model.toMap())))
        return if (raw["ok"] == true) AiRuntimeModelHandle(model.modelId, model.version, manifest.providerId, raw["metadata"] as? Map<String, Any> ?: emptyMap()) else null
    }

    override suspend fun unloadModel(handle: AiRuntimeModelHandle): Boolean = nativeUnloadModel(LocalAiJson.encodeMap(handle.metadata + mapOf("model_id" to handle.modelId, "version" to handle.version))).toBoolean()

    override suspend fun execute(request: AiExecutionRequest, reporter: AiProgressReporter): AiExecutionResult {
        reporter.report(0.10, "Preparing ${manifest.displayName}")
        val raw = LocalAiJson.decodeMap(nativeExecute(LocalAiJson.encodeMap(request.toNativeMap())))
        reporter.report(1.0, "${manifest.displayName} inference complete")
        return AiExecutionResult(
            ok = raw["ok"] as? Boolean ?: false,
            status = raw["status"]?.toString().orEmpty().ifBlank { "runtime_failure" },
            message = raw["message"]?.toString().orEmpty(),
            details = raw["details"] as? Map<String, Any> ?: emptyMap(),
        )
    }

    override suspend fun cancel(sessionId: String): Boolean = nativeCancel(sessionId).toBoolean()
    override suspend fun release(): Boolean = nativeRelease().toBoolean()
    override fun queryMemory(): Map<String, Any> = LocalAiJson.decodeMap(nativeMemory(manifest.providerId))
    override suspend fun benchmark(model: AiModelDescriptor): Map<String, Any> = LocalAiJson.decodeMap(nativeBenchmark(LocalAiJson.encodeMap(model.toMap())))

    private external fun nativeProbe(providerId: String): String
    private external fun nativeLoadModel(modelJson: String): String
    private external fun nativeUnloadModel(handleJson: String): String
    private external fun nativeExecute(requestJson: String): String
    private external fun nativeCancel(sessionId: String): String
    private external fun nativeRelease(): String
    private external fun nativeMemory(providerId: String): String
    private external fun nativeBenchmark(modelJson: String): String
}

private fun AiExecutionRequest.toNativeMap(): Map<String, Any> = mapOf(
    "session_id" to sessionId,
    "task_id" to taskId,
    "task_type" to taskType,
    "model_id" to modelId,
    "version" to version,
    "runtime_hint" to runtimeHint,
    "attempt" to attempt,
    "deadline_at_ms" to deadlineAtMs,
    "payload" to payload,
)