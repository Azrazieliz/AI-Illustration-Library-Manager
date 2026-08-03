package com.ailm.android.runtime

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.os.SystemClock
import android.provider.DocumentsContract
import android.util.Log
import androidx.documentfile.provider.DocumentFile
import java.io.File
import java.io.InputStream

class SafStorageProvider(
    context: Context,
) : StorageProvider {

    companion object {
        private const val TAG = "AilmSafStorageProvider"
        private const val TIMING_TAG = "AilmFileOpTiming"
    }

    private val appContext = context.applicationContext
    private val resolver: ContentResolver = appContext.contentResolver

    override fun walkTree(rootUri: String): Sequence<StorageNode> = sequence {
        val root = DocumentFile.fromTreeUri(appContext, Uri.parse(rootUri)) ?: return@sequence
        val stack = ArrayDeque<Pair<DocumentFile, String?>>()
        stack.add(root to null)

        while (stack.isNotEmpty()) {
            val (node, parentUri) = stack.removeLast()
            val name = node.name ?: node.uri.lastPathSegment ?: "unknown"
            val item = StorageNode(
                uri = node.uri.toString(),
                name = name,
                isDirectory = node.isDirectory,
                sizeBytes = if (node.isDirectory) null else node.length().takeIf { it >= 0L },
                lastModifiedMs = node.lastModified().takeIf { it > 0L },
                parentUri = parentUri,
            )
            yield(item)

            if (node.isDirectory) {
                val children = node.listFiles().toList()
                for (child: DocumentFile in children.asReversed()) {
                    stack.add(child to node.uri.toString())
                }
            }
        }
    }

    override fun openInputStream(uri: String): InputStream? {
        return resolver.openInputStream(Uri.parse(uri))
    }

    override fun listChildren(folderUri: String): List<StorageNode> {
        val cache = mutableMapOf<String, DocumentFile?>()
        val folder = resolveDocument(folderUri, cache) ?: return emptyList()
        if (!folder.isDirectory) {
            return emptyList()
        }
        return folder.listFiles().map { child ->
            StorageNode(
                uri = child.uri.toString(),
                name = child.name ?: child.uri.lastPathSegment ?: "unknown",
                isDirectory = child.isDirectory,
                sizeBytes = if (child.isDirectory) null else child.length().takeIf { it >= 0L },
                lastModifiedMs = child.lastModified().takeIf { it > 0L },
                parentUri = folder.uri.toString(),
            )
        }
    }

    override fun exists(uri: String): Boolean {
        val parsed = Uri.parse(uri)
        if (!hasPersistedTreePermission(parsed)) {
            Log.w(TAG, "Persisted SAF permission missing for $uri")
            return false
        }

        val treeDocument = DocumentFile.fromTreeUri(appContext, parsed)
        if (treeDocument != null) {
            return treeDocument.exists()
        }

        val document = DocumentFile.fromSingleUri(appContext, parsed)
        return document?.exists() == true
    }

    override fun rename(uri: String, newName: String): StorageWriteResult {
        val totalStart = SystemClock.elapsedRealtime()
        val cleaned = newName.trim()
        if (cleaned.isBlank()) {
            return StorageWriteResult(ok = false, message = "new name is required")
        }
        val cache = mutableMapOf<String, DocumentFile?>()
        val stage1Start = SystemClock.elapsedRealtime()
        val document = resolveDocument(uri, cache) ?: return StorageWriteResult(ok = false, message = "source not found")
        val stage1Ms = SystemClock.elapsedRealtime() - stage1Start

        val stage4Start = SystemClock.elapsedRealtime()
        val ok = document.renameTo(cleaned)
        val stage4Ms = SystemClock.elapsedRealtime() - stage4Start
        if (ok) {
            val totalMs = SystemClock.elapsedRealtime() - totalStart
            Log.d(TIMING_TAG, "rename stage1_resolve_source_ms=$stage1Ms")
            Log.d(TIMING_TAG, "rename stage2_resolve_destination_ms=0")
            Log.d(TIMING_TAG, "rename stage3_conflict_detection_ms=0")
            Log.d(TIMING_TAG, "rename stage4_saf_call_ms=$stage4Ms")
            Log.d(TIMING_TAG, "rename stage1to4_total_ms=$totalMs")
            return StorageWriteResult(ok = true, uri = document.uri.toString(), changed = true)
        }
        val stage3Start = SystemClock.elapsedRealtime()
        val parent = document.parentFile
        if (parent != null) {
            val sibling = parent.findFile(cleaned)
            val stage3Ms = SystemClock.elapsedRealtime() - stage3Start
            val totalMs = SystemClock.elapsedRealtime() - totalStart
            Log.d(TIMING_TAG, "rename stage1_resolve_source_ms=$stage1Ms")
            Log.d(TIMING_TAG, "rename stage2_resolve_destination_ms=0")
            Log.d(TIMING_TAG, "rename stage3_conflict_detection_ms=$stage3Ms")
            Log.d(TIMING_TAG, "rename stage4_saf_call_ms=$stage4Ms")
            Log.d(TIMING_TAG, "rename stage1to4_total_ms=$totalMs")
            if (sibling != null && sibling.uri != document.uri) {
                return StorageWriteResult(ok = false, message = "name conflict in folder")
            }
        } else {
            val totalMs = SystemClock.elapsedRealtime() - totalStart
            Log.d(TIMING_TAG, "rename stage1_resolve_source_ms=$stage1Ms")
            Log.d(TIMING_TAG, "rename stage2_resolve_destination_ms=0")
            Log.d(TIMING_TAG, "rename stage3_conflict_detection_ms=0")
            Log.d(TIMING_TAG, "rename stage4_saf_call_ms=$stage4Ms")
            Log.d(TIMING_TAG, "rename stage1to4_total_ms=$totalMs")
        }
        return StorageWriteResult(ok = false, message = "rename failed")
    }

    override fun createFolder(parentUri: String, folderName: String): StorageWriteResult {
        val cleaned = folderName.trim()
        if (cleaned.isBlank()) {
            return StorageWriteResult(ok = false, message = "folder name is required")
        }
        val cache = mutableMapOf<String, DocumentFile?>()
        val parent = resolveDocument(parentUri, cache) ?: return StorageWriteResult(ok = false, message = "parent not found")
        if (!parent.isDirectory) {
            return StorageWriteResult(ok = false, message = "parent is not a directory")
        }
        val created = parent.createDirectory(cleaned)
        if (created != null) {
            return StorageWriteResult(ok = true, uri = created.uri.toString(), changed = true)
        }
        val existing = parent.findFile(cleaned)
        if (existing != null && existing.isDirectory) {
            return StorageWriteResult(ok = true, uri = existing.uri.toString(), changed = false, message = "already exists")
        }
        if (existing != null) {
            return StorageWriteResult(ok = false, message = "file with same name exists")
        }
        return StorageWriteResult(ok = false, message = "folder create failed")
    }

    override fun delete(uri: String): StorageWriteResult {
        val cache = mutableMapOf<String, DocumentFile?>()
        val document = resolveDocument(uri, cache) ?: return StorageWriteResult(ok = false, message = "target not found")
        val ok = document.delete()
        return if (ok) {
            StorageWriteResult(ok = true, changed = true)
        } else {
            StorageWriteResult(ok = false, message = "delete failed")
        }
    }

    override fun copy(sourceUri: String, targetFolderUri: String, preferredName: String?): StorageWriteResult {
        val cache = mutableMapOf<String, DocumentFile?>()
        val source = resolveDocument(sourceUri, cache) ?: return StorageWriteResult(ok = false, message = "source not found")
        if (source.isDirectory) {
            return StorageWriteResult(ok = false, message = "directory copy is not supported")
        }
        val targetFolder = resolveDocument(targetFolderUri, cache) ?: return StorageWriteResult(ok = false, message = "target folder not found")
        if (!targetFolder.isDirectory) {
            return StorageWriteResult(ok = false, message = "target is not a directory")
        }
        return copyResolved(source, targetFolder, preferredName)
    }

    override fun move(sourceUri: String, targetFolderUri: String, preferredName: String?): StorageWriteResult {
        val totalStart = SystemClock.elapsedRealtime()
        val cache = mutableMapOf<String, DocumentFile?>()
        val stage1Start = SystemClock.elapsedRealtime()
        val source = resolveDocument(sourceUri, cache) ?: return StorageWriteResult(ok = false, message = "source not found")
        val stage1Ms = SystemClock.elapsedRealtime() - stage1Start
        val sourceParent = source.parentFile?.uri?.toString().orEmpty()

        val stage2Start = SystemClock.elapsedRealtime()
        val targetFolder = resolveDocument(targetFolderUri, cache) ?: return StorageWriteResult(ok = false, message = "target folder not found")
        val stage2Ms = SystemClock.elapsedRealtime() - stage2Start
        if (!targetFolder.isDirectory) {
            return StorageWriteResult(ok = false, message = "target is not a directory")
        }

        val requestedName = preferredName?.trim().orEmpty().ifBlank { source.name ?: "moved" }
        if (sourceParent == targetFolderUri) {
            val stage4Start = SystemClock.elapsedRealtime()
            val renamed = source.renameTo(requestedName)
            val stage4Ms = SystemClock.elapsedRealtime() - stage4Start
            if (renamed) {
                val totalMs = SystemClock.elapsedRealtime() - totalStart
                Log.d(TIMING_TAG, "move stage1_resolve_source_ms=$stage1Ms")
                Log.d(TIMING_TAG, "move stage2_resolve_destination_ms=$stage2Ms")
                Log.d(TIMING_TAG, "move stage3_conflict_detection_ms=0")
                Log.d(TIMING_TAG, "move stage4_saf_call_ms=$stage4Ms")
                Log.d(TIMING_TAG, "move stage1to4_total_ms=$totalMs")
                return StorageWriteResult(ok = true, uri = source.uri.toString(), changed = true)
            }
            val stage3Start = SystemClock.elapsedRealtime()
            val sibling = source.parentFile?.findFile(requestedName)
            val stage3Ms = SystemClock.elapsedRealtime() - stage3Start
            val totalMs = SystemClock.elapsedRealtime() - totalStart
            Log.d(TIMING_TAG, "move stage1_resolve_source_ms=$stage1Ms")
            Log.d(TIMING_TAG, "move stage2_resolve_destination_ms=$stage2Ms")
            Log.d(TIMING_TAG, "move stage3_conflict_detection_ms=$stage3Ms")
            Log.d(TIMING_TAG, "move stage4_saf_call_ms=$stage4Ms")
            Log.d(TIMING_TAG, "move stage1to4_total_ms=$totalMs")
            if (sibling != null && sibling.uri != source.uri) {
                return StorageWriteResult(ok = false, message = "name conflict in folder")
            }
            return StorageWriteResult(ok = false, message = "rename failed")
        }

        val stage4Start = SystemClock.elapsedRealtime()
        val copied = copyResolved(source, targetFolder, requestedName)
        val stage4Ms = SystemClock.elapsedRealtime() - stage4Start
        if (!copied.ok) {
            val totalMs = SystemClock.elapsedRealtime() - totalStart
            Log.d(TIMING_TAG, "move stage1_resolve_source_ms=$stage1Ms")
            Log.d(TIMING_TAG, "move stage2_resolve_destination_ms=$stage2Ms")
            Log.d(TIMING_TAG, "move stage3_conflict_detection_ms=0")
            Log.d(TIMING_TAG, "move stage4_saf_call_ms=$stage4Ms")
            Log.d(TIMING_TAG, "move stage1to4_total_ms=$totalMs")
            return copied
        }

        val copiedUri = copied.uri
        if (copiedUri.isNullOrBlank() || !verifyCopiedFile(source, copiedUri, cache)) {
            if (!copiedUri.isNullOrBlank()) {
                resolveDocument(copiedUri, cache)?.delete()
            }
            val totalMs = SystemClock.elapsedRealtime() - totalStart
            Log.d(TIMING_TAG, "move stage1_resolve_source_ms=$stage1Ms")
            Log.d(TIMING_TAG, "move stage2_resolve_destination_ms=$stage2Ms")
            Log.d(TIMING_TAG, "move stage3_conflict_detection_ms=0")
            Log.d(TIMING_TAG, "move stage4_saf_call_ms=$stage4Ms")
            Log.d(TIMING_TAG, "move stage1to4_total_ms=$totalMs")
            return StorageWriteResult(ok = false, message = "copied file verification failed")
        }

        val deleted = source.delete()
        val totalMs = SystemClock.elapsedRealtime() - totalStart
        Log.d(TIMING_TAG, "move stage1_resolve_source_ms=$stage1Ms")
        Log.d(TIMING_TAG, "move stage2_resolve_destination_ms=$stage2Ms")
        Log.d(TIMING_TAG, "move stage3_conflict_detection_ms=0")
        Log.d(TIMING_TAG, "move stage4_saf_call_ms=$stage4Ms")
        Log.d(TIMING_TAG, "move stage1to4_total_ms=$totalMs")
        if (!deleted) {
            return StorageWriteResult(ok = false, uri = copied.uri, message = "copied but failed to remove source")
        }
        return StorageWriteResult(ok = true, uri = copied.uri, changed = true)
    }

    private fun copyResolved(source: DocumentFile, targetFolder: DocumentFile, preferredName: String?): StorageWriteResult {
        val sourceName = source.name ?: source.uri.lastPathSegment ?: "copy"
        val requestedName = preferredName?.trim().orEmpty().ifBlank { sourceName }
        var finalName = requestedName
        val mime = resolver.getType(source.uri) ?: mimeFromName(finalName)
        var target = targetFolder.createFile(mime, finalName)
        if (target == null) {
            finalName = resolveUniqueName(targetFolder, requestedName)
            target = targetFolder.createFile(mime, finalName)
                ?: return StorageWriteResult(ok = false, message = "unable to create target file")
        }

        resolver.openInputStream(source.uri)?.use { input ->
            resolver.openOutputStream(target.uri, "w")?.use { output ->
                input.copyTo(output)
            } ?: return StorageWriteResult(ok = false, message = "unable to open output stream")
        } ?: return StorageWriteResult(ok = false, message = "unable to open input stream")

        return StorageWriteResult(ok = true, uri = target.uri.toString(), changed = true)
    }

    private fun verifyCopiedFile(
        source: DocumentFile,
        copiedUri: String,
        cache: MutableMap<String, DocumentFile?>,
    ): Boolean {
        val copied = resolveDocument(copiedUri, cache) ?: return false
        if (!copied.exists()) {
            return false
        }

        val sourceSize = source.length()
        val copiedSize = copied.length()
        if (sourceSize >= 0L && copiedSize >= 0L && sourceSize != copiedSize) {
            return false
        }

        return true
    }

    private fun resolveDocument(uri: String, cache: MutableMap<String, DocumentFile?>): DocumentFile? {
        cache[uri]?.let { return it }
        val parsed = Uri.parse(uri)
        val resolved = if (DocumentsContract.isTreeUri(parsed)) {
            DocumentFile.fromTreeUri(appContext, parsed)
        } else {
            DocumentFile.fromSingleUri(appContext, parsed) ?: DocumentFile.fromTreeUri(appContext, parsed)
        }
        cache[uri] = resolved
        return resolved
    }

    private fun resolveUniqueName(folder: DocumentFile, desiredName: String): String {
        val existing = folder.listFiles().mapNotNull { it.name?.lowercase() }.toHashSet()
        if (!existing.contains(desiredName.lowercase())) {
            return desiredName
        }
        val ext = File(desiredName).extension
        val base = if (ext.isBlank()) desiredName else desiredName.removeSuffix(".$ext")
        var index = 1
        while (true) {
            val candidate = if (ext.isBlank()) "$base ($index)" else "$base ($index).$ext"
            if (!existing.contains(candidate.lowercase())) {
                return candidate
            }
            index += 1
        }
    }

    private fun mimeFromName(name: String): String {
        return when (name.substringAfterLast('.', "").lowercase()) {
            "jpg", "jpeg" -> "image/jpeg"
            "png" -> "image/png"
            "gif" -> "image/gif"
            "webp" -> "image/webp"
            "bmp" -> "image/bmp"
            "tif", "tiff" -> "image/tiff"
            "heif", "heic" -> "image/heic"
            "avif" -> "image/avif"
            else -> "application/octet-stream"
        }
    }

    private fun hasPersistedTreePermission(uri: Uri): Boolean {
        val target = uri.normalizeScheme().toString()
        val permission = resolver.persistedUriPermissions.firstOrNull {
            it.uri.normalizeScheme().toString() == target
        } ?: return false
        return permission.isReadPermission && permission.isWritePermission
    }
}
