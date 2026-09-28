package com.ailm.android.runtime

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import java.io.File
import java.io.InputStream
import java.security.MessageDigest
import java.util.Locale
import java.util.zip.ZipInputStream

/**
 * Imports externally generated canonical character sheets from a flat ZIP.
 *
 * The user never has to create a Series/Character directory tree. Each sheet
 * filename is resolved against immutable Character Knowledge and stored in the
 * app's private immutable visual-Knowledge asset store.
 */
internal class CharacterSheetArchiveImporter(
    private val context: Context,
    private val knowledge: KnowledgeDatabase,
) {
    fun importZip(input: InputStream, sourceName: String): Map<String, Any> {
        val targetRoot = File(context.filesDir, "knowledge/character-sheets").apply { mkdirs() }
        var imported = 0
        var skipped = 0
        var duplicates = 0
        val unresolved = mutableListOf<String>()
        val seenCharacters = mutableSetOf<String>()

        ZipInputStream(input).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                val entryName = entry.name.substringAfterLast('/')
                if (entry.isDirectory || !isImage(entryName)) {
                    zip.closeEntry()
                    continue
                }

                val character = resolveFilename(entryName)
                if (character == null) {
                    skipped += 1
                    if (unresolved.size < MAX_REPORTED_ERRORS) unresolved += entryName
                    zip.closeEntry()
                    continue
                }
                if (!seenCharacters.add(character.characterId)) {
                    duplicates += 1
                    zip.closeEntry()
                    continue
                }

                val bytes = zip.readBytes()
                zip.closeEntry()
                val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                if (bitmap == null) {
                    skipped += 1
                    if (unresolved.size < MAX_REPORTED_ERRORS) unresolved += entryName + " (decode failed)"
                    continue
                }

                val output = File(targetRoot, character.characterId + ".webp")
                val ok = output.outputStream().use { stream ->
                    bitmap.compress(Bitmap.CompressFormat.WEBP_LOSSY, SHEET_WEBP_QUALITY, stream)
                }
                val width = bitmap.width
                val height = bitmap.height
                bitmap.recycle()
                if (!ok) {
                    skipped += 1
                    if (unresolved.size < MAX_REPORTED_ERRORS) unresolved += entryName + " (compression failed)"
                    output.delete()
                    continue
                }

                val sha = sha256(output)
                val sheetAssetId = "CS-" + character.characterId
                knowledge.attachCharacterSheet(
                    characterId = character.characterId,
                    sheetAssetId = sheetAssetId,
                    archiveName = sourceName,
                    assetPath = output.absolutePath,
                    sha256 = sha,
                    metadata = mapOf(
                        "source_filename" to entryName,
                        "width" to width,
                        "height" to height,
                        "storage_format" to "webp",
                        "quality" to SHEET_WEBP_QUALITY,
                    ),
                )
                imported += 1
            }
        }

        return mapOf(
            "ok" to (imported > 0 && unresolved.isEmpty()),
            "kind" to "character_sheet_archive",
            "source" to sourceName,
            "imported" to imported,
            "skipped" to skipped,
            "duplicate_character_sheets" to duplicates,
            "unresolved_files" to unresolved,
            "message" to when {
                imported == 0 -> "No character sheets could be resolved against Character Knowledge."
                unresolved.isNotEmpty() -> "Character sheets imported with unresolved filenames."
                duplicates > 0 -> "Character sheets imported; duplicate character sheets were skipped."
                else -> "Character sheets imported into immutable visual Knowledge."
            },
        )
    }

    private fun resolveFilename(filename: String): KnowledgeCharacterEntry? {
        val stem = filename.substringBeforeLast('.')
            .replace(Regex("\\s+\\d+$"), "")
            .trim()
        if (stem.isBlank()) return null

        val delimiter = " - "
        var index = stem.lastIndexOf(delimiter)
        while (index > 0) {
            val characterText = stem.substring(0, index).trim()
            val seriesText = stem.substring(index + delimiter.length).trim()
            val character = knowledge.resolveCharacter(characterText)
            val series = knowledge.resolveSeries(seriesText)
            if (character != null && series != null && character.primarySeriesCode == series.code) {
                return character
            }
            index = stem.lastIndexOf(delimiter, index - 1)
        }
        return null
    }

    private fun isImage(name: String): Boolean {
        val extension = name.substringAfterLast('.', "").lowercase(Locale.US)
        return extension in setOf("png", "jpg", "jpeg", "webp", "bmp")
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val count = input.read(buffer)
                if (count <= 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    companion object {
        private const val SHEET_WEBP_QUALITY = 85
        private const val MAX_REPORTED_ERRORS = 50
    }
}
