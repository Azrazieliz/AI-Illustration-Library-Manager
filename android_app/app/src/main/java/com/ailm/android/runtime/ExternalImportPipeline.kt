package com.ailm.android.runtime

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.ParseException
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

typealias ExternalImportProgressCallback = (Map<String, Any>) -> Unit

enum class ExternalImportSourceType {
    JSON,
    SQLITE,
    CSV,
    WORKBOOK_COMPAT_JSON,
}

enum class ExternalImportConflictStrategy {
    SKIP,
    OVERWRITE,
    KEEP_BOTH,
    MERGE_METADATA,
    RENAME_IMPORTED,
}

data class ExternalImportRequest(
    val importId: String = UUID.randomUUID().toString(),
    val sourceType: ExternalImportSourceType,
    val source: String,
    val conflictStrategy: ExternalImportConflictStrategy = ExternalImportConflictStrategy.MERGE_METADATA,
    val replaceExisting: Boolean = false,
    val csvTableName: String? = null,
    val aliasHints: Map<String, Map<String, String>> = emptyMap(),
)

data class ExternalImportDuplicateCandidate(
    val duplicateType: String,
    val tableName: String,
    val key: String,
    val importedValue: String,
    val existingValue: String?,
    val details: String,
) {
    fun toMap(): Map<String, Any> {
        return mapOf(
            "duplicate_type" to duplicateType,
            "table" to tableName,
            "key" to key,
            "imported_value" to importedValue,
            "existing_value" to (existingValue ?: ""),
            "details" to details,
        )
    }
}

data class ExternalImportConflict(
    val tableName: String,
    val key: String,
    val reason: String,
    val strategy: ExternalImportConflictStrategy,
    val decision: String,
) {
    fun toMap(): Map<String, Any> {
        return mapOf(
            "table" to tableName,
            "key" to key,
            "reason" to reason,
            "strategy" to strategy.name.lowercase(),
            "decision" to decision,
        )
    }
}

data class ExternalImportObjectDelta(
    val tableName: String,
    val key: String,
    val action: String,
    val reason: String,
) {
    fun toMap(): Map<String, Any> {
        return mapOf(
            "table" to tableName,
            "key" to key,
            "action" to action,
            "reason" to reason,
        )
    }
}

data class ExternalImportPreview(
    val importId: String,
    val sourceType: ExternalImportSourceType,
    val replaceExisting: Boolean,
    val objectsToCreate: List<ExternalImportObjectDelta>,
    val objectsToUpdate: List<ExternalImportObjectDelta>,
    val objectsToSkip: List<ExternalImportObjectDelta>,
    val duplicates: List<ExternalImportDuplicateCandidate>,
    val conflicts: List<ExternalImportConflict>,
    val warnings: List<String>,
    val summaryStatistics: Map<String, Any>,
) {
    fun toMap(): Map<String, Any> {
        return mapOf(
            "import_id" to importId,
            "source_type" to sourceType.name.lowercase(),
            "replace_existing" to replaceExisting,
            "objects_to_create" to objectsToCreate.map { it.toMap() },
            "objects_to_update" to objectsToUpdate.map { it.toMap() },
            "objects_to_skip" to objectsToSkip.map { it.toMap() },
            "duplicates" to duplicates.map { it.toMap() },
            "conflicts" to conflicts.map { it.toMap() },
            "warnings" to warnings,
            "summary_statistics" to summaryStatistics,
        )
    }
}

data class ExternalImportExecutionResult(
    val ok: Boolean,
    val importId: String,
    val status: String,
    val preview: ExternalImportPreview,
    val validation: FusionValidationReport,
    val appliedCreates: Int,
    val appliedUpdates: Int,
    val appliedSkips: Int,
    val warnings: List<String>,
    val errorMessage: String = "",
) {
    fun toMap(): Map<String, Any> {
        return mapOf(
            "ok" to ok,
            "import_id" to importId,
            "status" to status,
            "preview" to preview.toMap(),
            "validation" to validation.toMap(),
            "applied_creates" to appliedCreates,
            "applied_updates" to appliedUpdates,
            "applied_skips" to appliedSkips,
            "warnings" to warnings,
            "error_message" to errorMessage,
        )
    }

    fun toFusionImportResult(format: FusionImportFormat): FusionImportResult {
        val duplicatePayloadDetails = preview.duplicates
            .filter { it.duplicateType == "immutable_id_source" }
            .map { "${it.tableName}:${it.key}" }
        return FusionImportResult(
            ok = ok,
            format = format,
            replaceExisting = preview.replaceExisting,
            importedRows = appliedCreates + appliedUpdates,
            touchedTables = preview.summaryStatistics["touched_tables"] as? Int ?: 0,
            duplicatePayloadIds = duplicatePayloadDetails.size,
            duplicatePayloadDetails = duplicatePayloadDetails,
            validation = validation,
        )
    }
}

class ExternalImportPipeline(
    private val database: LocalDatabase,
    workbookSheetToTable: Map<String, String>,
) {
    private companion object {
        private const val TAG = "AilmExternalImport"
        private const val SNAPSHOT_FORMAT = "fusion_json"
    }

    private data class TableSchema(
        val tableName: String,
        val columns: List<ColumnSchema>,
        val primaryKeyColumns: List<String>,
    )

    private data class ColumnSchema(
        val name: String,
        val typeAffinity: String,
        val notNull: Boolean,
        val defaultValue: String?,
        val pkPosition: Int,
    )

    private enum class MergeAction {
        CREATE,
        UPDATE,
        SKIP,
    }

    private data class ResolvedRow(
        val tableName: String,
        val key: String,
        val action: MergeAction,
        val row: MutableMap<String, Any?>,
        val reason: String,
    )

    private data class RawImportPayload(
        val sourceType: ExternalImportSourceType,
        val sourceLabel: String,
        val tableRows: Map<String, JSONArray>,
        val imageSnapshot: JSONArray,
    )

    private data class CanonicalImportModel(
        val importId: String,
        val sourceType: ExternalImportSourceType,
        val sourceLabel: String,
        val rowsByTable: MutableMap<String, MutableList<MutableMap<String, Any?>>>,
        val imageSnapshotRows: MutableList<MutableMap<String, Any?>>, 
    )

    private data class PipelineContext(
        val model: CanonicalImportModel,
        val resolvedRows: List<ResolvedRow>,
        val duplicates: List<ExternalImportDuplicateCandidate>,
        val conflicts: List<ExternalImportConflict>,
        val warnings: List<String>,
        val validation: FusionValidationReport,
        val preview: ExternalImportPreview,
    )

    private class ImportCancelledException(message: String) : RuntimeException(message)

    private val sheetToTableLookup: Map<String, String> = workbookSheetToTable
        .mapKeys { it.key.lowercase(Locale.US) }

    private val tableNamesByLower: Map<String, String> = FusionDatabaseSchema.DOMAIN_TABLE_ORDER
        .associateBy { it.lowercase(Locale.US) }

    private val supportedTables: Set<String> = FusionDatabaseSchema.DOMAIN_TABLE_ORDER.toSet()

    private val importLock = Any()
    private val cancelFlags = ConcurrentHashMap<String, Boolean>()

    @Volatile
    private var activeImportId: String? = null

    private val nameColumnByTable: Map<String, String> = mapOf(
        FusionDatabaseSchema.TABLE_FRANCHISES to "display_name",
        FusionDatabaseSchema.TABLE_SERIES to "canonical_title",
        FusionDatabaseSchema.TABLE_CHARACTERS to "canonical_name",
        FusionDatabaseSchema.TABLE_TAGS to "canonical_name",
        FusionDatabaseSchema.TABLE_OUTFITS to "canonical_name",
        FusionDatabaseSchema.TABLE_WEAPONS to "canonical_name",
        FusionDatabaseSchema.TABLE_ARTISTS to "display_name",
        FusionDatabaseSchema.TABLE_COLLECTIONS to "collection_name",
    )

    private val idColumnByTable: Map<String, String> = mapOf(
        FusionDatabaseSchema.TABLE_FRANCHISES to "franchise_id",
        FusionDatabaseSchema.TABLE_SERIES to "series_code",
        FusionDatabaseSchema.TABLE_CHARACTERS to "character_id",
        FusionDatabaseSchema.TABLE_TAGS to "tag_id",
        FusionDatabaseSchema.TABLE_TAG_ALIASES to "alias_id",
        FusionDatabaseSchema.TABLE_OUTFITS to "outfit_id",
        FusionDatabaseSchema.TABLE_WEAPONS to "weapon_id",
        FusionDatabaseSchema.TABLE_ARTISTS to "artist_id",
        FusionDatabaseSchema.TABLE_COLLECTIONS to "collection_id",
    )

    private val relationRules: List<RelationRule> = listOf(
        RelationRule(FusionDatabaseSchema.TABLE_SERIES, "franchise_id", FusionDatabaseSchema.TABLE_FRANCHISES, "franchise_id"),
        RelationRule(FusionDatabaseSchema.TABLE_SERIES, "parent_series_code", FusionDatabaseSchema.TABLE_SERIES, "series_code"),
        RelationRule(FusionDatabaseSchema.TABLE_CHARACTERS, "primary_series_code", FusionDatabaseSchema.TABLE_SERIES, "series_code"),
        RelationRule(FusionDatabaseSchema.TABLE_CHARACTER_SERIES, "character_id", FusionDatabaseSchema.TABLE_CHARACTERS, "character_id"),
        RelationRule(FusionDatabaseSchema.TABLE_CHARACTER_SERIES, "series_code", FusionDatabaseSchema.TABLE_SERIES, "series_code"),
        RelationRule(FusionDatabaseSchema.TABLE_TAGS, "parent_tag_id", FusionDatabaseSchema.TABLE_TAGS, "tag_id"),
        RelationRule(FusionDatabaseSchema.TABLE_TAG_ALIASES, "tag_id", FusionDatabaseSchema.TABLE_TAGS, "tag_id"),
        RelationRule(FusionDatabaseSchema.TABLE_COLLECTIONS, "parent_collection_id", FusionDatabaseSchema.TABLE_COLLECTIONS, "collection_id"),
        RelationRule(FusionDatabaseSchema.TABLE_COLLECTION_IMAGES, "collection_id", FusionDatabaseSchema.TABLE_COLLECTIONS, "collection_id"),
        RelationRule(FusionDatabaseSchema.TABLE_COLLECTION_IMAGES, "image_id", "images", "image_id"),
        RelationRule(FusionDatabaseSchema.TABLE_CHARACTER_OUTFITS, "character_id", FusionDatabaseSchema.TABLE_CHARACTERS, "character_id"),
        RelationRule(FusionDatabaseSchema.TABLE_CHARACTER_OUTFITS, "outfit_id", FusionDatabaseSchema.TABLE_OUTFITS, "outfit_id"),
        RelationRule(FusionDatabaseSchema.TABLE_CHARACTER_WEAPONS, "character_id", FusionDatabaseSchema.TABLE_CHARACTERS, "character_id"),
        RelationRule(FusionDatabaseSchema.TABLE_CHARACTER_WEAPONS, "weapon_id", FusionDatabaseSchema.TABLE_WEAPONS, "weapon_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_PROFILES, "image_id", "images", "image_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_SERIES, "image_id", "images", "image_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_SERIES, "series_code", FusionDatabaseSchema.TABLE_SERIES, "series_code"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_CHARACTERS, "image_id", "images", "image_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_CHARACTERS, "character_id", FusionDatabaseSchema.TABLE_CHARACTERS, "character_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_TAGS, "image_id", "images", "image_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_TAGS, "tag_id", FusionDatabaseSchema.TABLE_TAGS, "tag_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_OUTFITS, "image_id", "images", "image_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_OUTFITS, "outfit_id", FusionDatabaseSchema.TABLE_OUTFITS, "outfit_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_WEAPONS, "image_id", "images", "image_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_WEAPONS, "weapon_id", FusionDatabaseSchema.TABLE_WEAPONS, "weapon_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_ARTISTS, "image_id", "images", "image_id"),
        RelationRule(FusionDatabaseSchema.TABLE_IMAGE_ARTISTS, "artist_id", FusionDatabaseSchema.TABLE_ARTISTS, "artist_id"),
    )

    private val enumRules: Map<Pair<String, String>, Set<String>> = mapOf(
        Pair(FusionDatabaseSchema.TABLE_COLLECTIONS, "collection_kind") to setOf("manual", "smart", "dynamic"),
        Pair(FusionDatabaseSchema.TABLE_SERIES_LINKS, "relation_kind") to setOf("related", "spinoff", "prequel", "sequel", "alternate", "shared"),
        Pair(FusionDatabaseSchema.TABLE_CHARACTER_SERIES, "relation_kind") to setOf("primary", "secondary", "guest", "alternate"),
        Pair(FusionDatabaseSchema.TABLE_CHARACTER_OUTFITS, "relation_kind") to setOf("canonical", "variant", "temporary", "other"),
        Pair(FusionDatabaseSchema.TABLE_CHARACTER_WEAPONS, "relation_kind") to setOf("canonical", "variant", "temporary", "other"),
    )

    private data class RelationRule(
        val tableName: String,
        val columnName: String,
        val targetTable: String,
        val targetColumn: String,
    )

    private interface ImportReader {
        fun read(request: ExternalImportRequest): RawImportPayload
    }

    private inner class UnifiedReader : ImportReader {
        private val readers: Map<ExternalImportSourceType, ImportReader> = mapOf(
            ExternalImportSourceType.JSON to JsonReader(),
            ExternalImportSourceType.WORKBOOK_COMPAT_JSON to WorkbookJsonReader(),
            ExternalImportSourceType.CSV to CsvReader(),
            ExternalImportSourceType.SQLITE to SqliteReader(),
        )

        override fun read(request: ExternalImportRequest): RawImportPayload {
            return readers[request.sourceType]?.read(request)
                ?: throw IllegalArgumentException("Unsupported source type: ${request.sourceType}")
        }
    }

    private inner class JsonReader : ImportReader {
        override fun read(request: ExternalImportRequest): RawImportPayload {
            val text = readSourceContent(request.source)
            val parsed = JSONObject(text)
            val tableRows = mutableMapOf<String, JSONArray>()
            val tables = parsed.optJSONObject("tables")

            if (tables != null) {
                val keys = tables.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    val value = tables.optJSONArray(key) ?: continue
                    resolveTableName(key)?.let { tableRows[it] = value }
                }
            } else {
                val keys = parsed.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    if (key == "images_snapshot" || key == "format" || key == "fusion_schema_version" || key == "generated_at_ms") {
                        continue
                    }
                    val value = parsed.optJSONArray(key) ?: continue
                    resolveTableName(key)?.let { tableRows[it] = value }
                }
            }

            val imageSnapshot = parsed.optJSONArray("images_snapshot") ?: JSONArray()
            return RawImportPayload(
                sourceType = request.sourceType,
                sourceLabel = sourceLabel(request.source),
                tableRows = tableRows,
                imageSnapshot = imageSnapshot,
            )
        }
    }

    private inner class WorkbookJsonReader : ImportReader {
        override fun read(request: ExternalImportRequest): RawImportPayload {
            val text = readSourceContent(request.source)
            val parsed = JSONObject(text)
            val sheets = parsed.optJSONObject("sheets") ?: JSONObject()
            val tableRows = mutableMapOf<String, JSONArray>()

            val keys = sheets.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                val value = sheets.optJSONArray(key) ?: continue
                val mapped = resolveWorkbookSheet(key) ?: continue
                tableRows[mapped] = value
            }

            val imageSnapshot = parsed.optJSONArray("images_snapshot") ?: JSONArray()
            return RawImportPayload(
                sourceType = request.sourceType,
                sourceLabel = sourceLabel(request.source),
                tableRows = tableRows,
                imageSnapshot = imageSnapshot,
            )
        }
    }

    private inner class CsvReader : ImportReader {
        override fun read(request: ExternalImportRequest): RawImportPayload {
            val content = readSourceContent(request.source)
            val rows = parseCsv(content)
            if (rows.isEmpty()) {
                return RawImportPayload(
                    sourceType = request.sourceType,
                    sourceLabel = sourceLabel(request.source),
                    tableRows = emptyMap(),
                    imageSnapshot = JSONArray(),
                )
            }

            val header = rows.first()
            val dataRows = rows.drop(1)
            val tableRows = mutableMapOf<String, MutableList<JSONObject>>()
            val tableNameIndex = header.indexOfFirst {
                val lower = it.trim().lowercase(Locale.US)
                lower == "table" || lower == "table_name" || lower == "__table"
            }

            dataRows.forEach { rowValues ->
                val rowObject = JSONObject()
                header.forEachIndexed { index, column ->
                    if (index >= rowValues.size) {
                        rowObject.put(column, JSONObject.NULL)
                    } else {
                        rowObject.put(column, rowValues[index])
                    }
                }

                val rawTableName = when {
                    tableNameIndex >= 0 && tableNameIndex < rowValues.size -> rowValues[tableNameIndex]
                    !request.csvTableName.isNullOrBlank() -> request.csvTableName
                    else -> ""
                }
                val mappedTableName = resolveTableName(rawTableName)
                    ?: resolveWorkbookSheet(rawTableName)
                    ?: return@forEach

                rowObject.remove("table")
                rowObject.remove("table_name")
                rowObject.remove("__table")
                tableRows.getOrPut(mappedTableName) { mutableListOf() }.add(rowObject)
            }

            val normalizedMap = tableRows.mapValues { (_, values) ->
                JSONArray().apply {
                    values.forEach { put(it) }
                }
            }

            return RawImportPayload(
                sourceType = request.sourceType,
                sourceLabel = sourceLabel(request.source),
                tableRows = normalizedMap,
                imageSnapshot = JSONArray(),
            )
        }
    }

    private inner class SqliteReader : ImportReader {
        override fun read(request: ExternalImportRequest): RawImportPayload {
            val path = request.source.trim()
            val file = File(path)
            require(file.exists()) { "SQLite source not found: $path" }

            val tableRows = mutableMapOf<String, JSONArray>()
            var imageSnapshot = JSONArray()
            val readDb = SQLiteDatabase.openDatabase(file.absolutePath, null, SQLiteDatabase.OPEN_READONLY)
            try {
                val availableTables = mutableSetOf<String>()
                readDb.rawQuery(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
                    emptyArray(),
                ).use { cursor ->
                    while (cursor.moveToNext()) {
                        availableTables.add(cursor.getString(0))
                    }
                }

                availableTables.forEach { originalName ->
                    val mapped = resolveTableName(originalName) ?: resolveWorkbookSheet(originalName)
                    if (mapped != null && supportedTables.contains(mapped)) {
                        tableRows[mapped] = readTableRows(readDb, originalName)
                    }
                }

                if (availableTables.contains("images")) {
                    imageSnapshot = readImageSnapshot(readDb)
                }
            } finally {
                readDb.close()
            }

            return RawImportPayload(
                sourceType = request.sourceType,
                sourceLabel = file.absolutePath,
                tableRows = tableRows,
                imageSnapshot = imageSnapshot,
            )
        }

        private fun readTableRows(db: SQLiteDatabase, tableName: String): JSONArray {
            val result = JSONArray()
            db.rawQuery("SELECT * FROM $tableName", emptyArray()).use { cursor ->
                while (cursor.moveToNext()) {
                    val row = JSONObject()
                    for (index in 0 until cursor.columnCount) {
                        val name = cursor.getColumnName(index)
                        if (cursor.isNull(index)) {
                            row.put(name, JSONObject.NULL)
                        } else {
                            when (cursor.getType(index)) {
                                Cursor.FIELD_TYPE_INTEGER -> row.put(name, cursor.getLong(index))
                                Cursor.FIELD_TYPE_FLOAT -> row.put(name, cursor.getDouble(index))
                                else -> row.put(name, cursor.getString(index))
                            }
                        }
                    }
                    result.put(row)
                }
            }
            return result
        }

        private fun readImageSnapshot(db: SQLiteDatabase): JSONArray {
            val result = JSONArray()
            val sql = """
                SELECT image_id, uri, filename, folder_uri, metadata_text
                FROM images
            """.trimIndent()
            db.rawQuery(sql, emptyArray()).use { cursor ->
                while (cursor.moveToNext()) {
                    val row = JSONObject()
                    row.put("image_id", cursor.getInt(0))
                    row.put("uri", cursor.getString(1))
                    row.put("filename", cursor.getString(2))
                    row.put("folder_uri", cursor.getString(3))
                    row.put("metadata_text", cursor.getString(4) ?: "")
                    result.put(row)
                }
            }
            return result
        }
    }

    fun previewImport(
        request: ExternalImportRequest,
        callback: ExternalImportProgressCallback? = null,
    ): ExternalImportPreview {
        val context = buildPipelineContext(request, callback)
        return context.preview
    }

    fun validateImport(
        request: ExternalImportRequest,
        callback: ExternalImportProgressCallback? = null,
    ): FusionValidationReport {
        val context = buildPipelineContext(request, callback)
        return context.validation
    }

    fun importDatabase(
        request: ExternalImportRequest,
        callback: ExternalImportProgressCallback? = null,
    ): ExternalImportExecutionResult {
        synchronized(importLock) {
            if (activeImportId != null) {
                val existingId = activeImportId.orEmpty()
                val emptyPreview = emptyPreview(request)
                val validation = emptyValidationReport("busy")
                return ExternalImportExecutionResult(
                    ok = false,
                    importId = request.importId,
                    status = "busy",
                    preview = emptyPreview,
                    validation = validation,
                    appliedCreates = 0,
                    appliedUpdates = 0,
                    appliedSkips = 0,
                    warnings = listOf("Another import is running: $existingId"),
                    errorMessage = "import busy",
                )
            }
            activeImportId = request.importId
        }

        cancelFlags.remove(request.importId)
        var beforeSnapshot = ""
        var context: PipelineContext? = null
        val startedAtMs = System.currentTimeMillis()
        try {
            emitProgress(callback, request.importId, "pipeline", 0.01, "Preparing import")
            context = buildPipelineContext(request, callback)
            checkCancellation(request.importId)

            beforeSnapshot = exportFusionSnapshotJson(pretty = false)
            recordImportRunStart(request, startedAtMs, beforeSnapshot)

            if (!context.validation.valid) {
                val result = ExternalImportExecutionResult(
                    ok = false,
                    importId = request.importId,
                    status = "validation_failed",
                    preview = context.preview,
                    validation = context.validation,
                    appliedCreates = 0,
                    appliedUpdates = 0,
                    appliedSkips = context.preview.objectsToSkip.size,
                    warnings = context.warnings,
                    errorMessage = "Validation failed",
                )
                recordImportRunFinish(
                    importId = request.importId,
                    status = result.status,
                    finishedAtMs = System.currentTimeMillis(),
                    summaryJson = JSONObject(result.toMap()).toString(),
                    afterSnapshotJson = "",
                    errorMessage = result.errorMessage,
                )
                return result
            }

            emitProgress(callback, request.importId, "merge", 0.75, "Applying merge")
            val merge = MergeEngine().apply(
                request = request,
                rows = context.resolvedRows,
                callback = callback,
            )
            checkCancellation(request.importId)

            val afterSnapshot = exportFusionSnapshotJson(pretty = false)
            val result = ExternalImportExecutionResult(
                ok = true,
                importId = request.importId,
                status = "completed",
                preview = context.preview,
                validation = context.validation,
                appliedCreates = merge.createdCount,
                appliedUpdates = merge.updatedCount,
                appliedSkips = context.preview.objectsToSkip.size,
                warnings = context.warnings,
            )

            recordImportRunFinish(
                importId = request.importId,
                status = result.status,
                finishedAtMs = System.currentTimeMillis(),
                summaryJson = JSONObject(result.toMap()).toString(),
                afterSnapshotJson = afterSnapshot,
                errorMessage = "",
            )
            emitProgress(callback, request.importId, "completed", 1.0, "Import completed")
            return result
        } catch (cancelled: ImportCancelledException) {
            val preview = context?.preview ?: emptyPreview(request)
            val validation = context?.validation ?: emptyValidationReport("cancelled")
            val result = ExternalImportExecutionResult(
                ok = false,
                importId = request.importId,
                status = "cancelled",
                preview = preview,
                validation = validation,
                appliedCreates = 0,
                appliedUpdates = 0,
                appliedSkips = preview.objectsToSkip.size,
                warnings = (context?.warnings ?: emptyList()) + cancelled.message.orEmpty(),
                errorMessage = cancelled.message.orEmpty(),
            )
            recordImportRunFinish(
                importId = request.importId,
                status = result.status,
                finishedAtMs = System.currentTimeMillis(),
                summaryJson = JSONObject(result.toMap()).toString(),
                afterSnapshotJson = "",
                errorMessage = result.errorMessage,
            )
            emitProgress(callback, request.importId, "cancelled", 1.0, "Import cancelled")
            return result
        } catch (t: Throwable) {
            Log.e(TAG, "Import failed", t)
            val preview = context?.preview ?: emptyPreview(request)
            val validation = context?.validation ?: emptyValidationReport("failed")
            val result = ExternalImportExecutionResult(
                ok = false,
                importId = request.importId,
                status = "failed",
                preview = preview,
                validation = validation,
                appliedCreates = 0,
                appliedUpdates = 0,
                appliedSkips = preview.objectsToSkip.size,
                warnings = context?.warnings ?: emptyList(),
                errorMessage = t.message ?: t.javaClass.simpleName,
            )
            recordImportRunFinish(
                importId = request.importId,
                status = result.status,
                finishedAtMs = System.currentTimeMillis(),
                summaryJson = JSONObject(result.toMap()).toString(),
                afterSnapshotJson = "",
                errorMessage = result.errorMessage,
            )
            emitProgress(callback, request.importId, "failed", 1.0, "Import failed")
            return result
        } finally {
            activeImportId = null
            cancelFlags.remove(request.importId)
            emitProgress(
                callback,
                request.importId,
                "finalized",
                1.0,
                "Import finalized",
                processed = 0,
                total = 0,
                startedAtMs = startedAtMs,
            )
        }
    }

    fun cancelImport(importId: String): Boolean {
        val normalized = importId.trim()
        if (normalized.isBlank()) {
            return false
        }
        cancelFlags[normalized] = true
        return true
    }

    fun rollbackImport(
        importId: String?,
        callback: ExternalImportProgressCallback? = null,
    ): ExternalImportExecutionResult {
        val run = findRollbackCandidate(importId)
        if (run == null) {
            val request = ExternalImportRequest(
                importId = "rollback-${UUID.randomUUID()}",
                sourceType = ExternalImportSourceType.JSON,
                source = "{}",
            )
            return ExternalImportExecutionResult(
                ok = false,
                importId = request.importId,
                status = "rollback_unavailable",
                preview = emptyPreview(request),
                validation = emptyValidationReport("rollback"),
                appliedCreates = 0,
                appliedUpdates = 0,
                appliedSkips = 0,
                warnings = emptyList(),
                errorMessage = "No successful import run available for rollback",
            )
        }

        val rollbackRequest = ExternalImportRequest(
            importId = "rollback-${UUID.randomUUID()}",
            sourceType = ExternalImportSourceType.JSON,
            source = run.beforeSnapshot,
            conflictStrategy = ExternalImportConflictStrategy.OVERWRITE,
            replaceExisting = true,
        )
        val result = importDatabase(rollbackRequest, callback)
        if (result.ok) {
            markRolledBack(run.importId, rollbackRequest.importId)
        }
        return result
    }

    private data class RollbackCandidate(
        val importId: String,
        val beforeSnapshot: String,
    )

    private data class MergeStats(
        val createdCount: Int,
        val updatedCount: Int,
    )

    private inner class MergeEngine {
        fun apply(
            request: ExternalImportRequest,
            rows: List<ResolvedRow>,
            callback: ExternalImportProgressCallback?,
        ): MergeStats {
            val db = database.writableDatabase
            val writableRows = rows.filter { it.action == MergeAction.CREATE || it.action == MergeAction.UPDATE }
            val total = writableRows.size.coerceAtLeast(1)
            var processed = 0
            var created = 0
            var updated = 0

            val grouped = writableRows.groupBy { it.tableName }
            db.beginTransaction()
            try {
                if (request.replaceExisting) {
                    clearFusionTables(db)
                }

                FusionDatabaseSchema.DOMAIN_TABLE_ORDER.forEach { tableName ->
                    val tableRows = grouped[tableName].orEmpty()
                    if (tableRows.isEmpty()) {
                        return@forEach
                    }

                    checkCancellation(request.importId)
                    val schema = loadTableSchema(tableName)
                    val columns = schema.columns.map { it.name }
                    val statement = db.compileStatement(buildUpsertSql(tableName, columns))
                    try {
                        tableRows.forEach { row ->
                            statement.clearBindings()
                            columns.forEachIndexed { index, columnName ->
                                bindSqlValue(statement, index + 1, row.row[columnName])
                            }
                            statement.executeInsert()
                            processed += 1
                            if (row.action == MergeAction.CREATE) {
                                created += 1
                            } else {
                                updated += 1
                            }
                            if (processed % 100 == 0 || processed == total) {
                                emitProgress(
                                    callback,
                                    request.importId,
                                    "merge",
                                    0.75 + (0.20 * processed.toDouble() / total.toDouble()),
                                    "Merged $processed/$total rows",
                                    processed = processed,
                                    total = total,
                                )
                            }
                            checkCancellation(request.importId)
                        }
                    } finally {
                        statement.close()
                    }
                }

                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }

            return MergeStats(createdCount = created, updatedCount = updated)
        }
    }

    private fun buildPipelineContext(
        request: ExternalImportRequest,
        callback: ExternalImportProgressCallback?,
    ): PipelineContext {
        val warnings = mutableListOf<String>()

        emitProgress(callback, request.importId, "reader", 0.05, "Reading source")
        checkCancellation(request.importId)
        val rawPayload = UnifiedReader().read(request)

        emitProgress(callback, request.importId, "parser", 0.15, "Parsing source")
        checkCancellation(request.importId)
        val model = parseCanonicalModel(request, rawPayload)

        emitProgress(callback, request.importId, "normalizer", 0.30, "Normalizing values")
        checkCancellation(request.importId)
        normalizeModel(model, warnings)

        emitProgress(callback, request.importId, "alias_resolver", 0.42, "Resolving aliases")
        checkCancellation(request.importId)
        resolveAliases(model, request, warnings)

        emitProgress(callback, request.importId, "taxonomy_resolver", 0.50, "Resolving taxonomy")
        checkCancellation(request.importId)
        val taxonomyIssues = resolveTaxonomy(model)

        emitProgress(callback, request.importId, "duplicate_detection", 0.58, "Detecting duplicates")
        checkCancellation(request.importId)
        val duplicates = detectDuplicates(model)

        emitProgress(callback, request.importId, "conflict_resolver", 0.66, "Resolving conflicts")
        checkCancellation(request.importId)
        val conflictResolution = resolveConflicts(model, request, duplicates)

        warnings += taxonomyIssues
        warnings += conflictResolution.warnings

        emitProgress(callback, request.importId, "validation", 0.72, "Validating import")
        checkCancellation(request.importId)
        val validation = validatePreparedImport(
            model = model,
            duplicates = duplicates,
            conflicts = conflictResolution.conflicts,
            warnings = warnings,
        )

        val preview = buildPreview(
            request = request,
            resolvedRows = conflictResolution.rows,
            duplicates = duplicates,
            conflicts = conflictResolution.conflicts,
            warnings = warnings,
        )

        return PipelineContext(
            model = model,
            resolvedRows = conflictResolution.rows,
            duplicates = duplicates,
            conflicts = conflictResolution.conflicts,
            warnings = warnings.distinct(),
            validation = validation,
            preview = preview,
        )
    }

    private fun parseCanonicalModel(
        request: ExternalImportRequest,
        rawPayload: RawImportPayload,
    ): CanonicalImportModel {
        val rowsByTable = mutableMapOf<String, MutableList<MutableMap<String, Any?>>>()

        rawPayload.tableRows.forEach { (tableName, rows) ->
            if (!supportedTables.contains(tableName)) {
                return@forEach
            }
            val mappedRows = mutableListOf<MutableMap<String, Any?>>()
            for (index in 0 until rows.length()) {
                val sourceRow = rows.optJSONObject(index) ?: continue
                val mapped = mutableMapOf<String, Any?>()
                val keys = sourceRow.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    val value = sourceRow.opt(key)
                    mapped[key] = if (value == JSONObject.NULL) null else value
                }
                mappedRows += mapped
            }
            rowsByTable[tableName] = mappedRows
        }

        val imageSnapshotRows = mutableListOf<MutableMap<String, Any?>>()
        for (index in 0 until rawPayload.imageSnapshot.length()) {
            val sourceRow = rawPayload.imageSnapshot.optJSONObject(index) ?: continue
            val mapped = mutableMapOf<String, Any?>()
            val keys = sourceRow.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                val value = sourceRow.opt(key)
                mapped[key] = if (value == JSONObject.NULL) null else value
            }
            imageSnapshotRows += mapped
        }

        return CanonicalImportModel(
            importId = request.importId,
            sourceType = request.sourceType,
            sourceLabel = rawPayload.sourceLabel,
            rowsByTable = rowsByTable,
            imageSnapshotRows = imageSnapshotRows,
        )
    }

    private fun normalizeModel(
        model: CanonicalImportModel,
        warnings: MutableList<String>,
    ) {
        model.rowsByTable.forEach { (tableName, rows) ->
            val schema = loadTableSchema(tableName)
            val columnLookup = schema.columns.associateBy { it.name.lowercase(Locale.US) }
            rows.forEachIndexed { index, row ->
                val normalizedRow = mutableMapOf<String, Any?>()
                schema.columns.forEach { column ->
                    val rawValue = findCaseInsensitive(row, column.name)
                    val normalized = normalizeValue(column, rawValue)
                    normalizedRow[column.name] = normalized
                }

                row.clear()
                row.putAll(normalizedRow)

                normalizeNameFields(tableName, row)
                normalizePathFields(row)

                columnLookup.values.forEach { column ->
                    if (column.notNull && row[column.name] == null) {
                        warnings += "$tableName row ${index + 1}: required column ${column.name} is null"
                    }
                }
            }
        }

        model.imageSnapshotRows.forEach { row ->
            normalizePathFields(row)
            val filename = findCaseInsensitive(row, "filename")?.toString().orEmpty()
            if (filename.isNotBlank()) {
                row["filename"] = normalizeDisplayName(filename)
            }
        }
    }

    private fun normalizeNameFields(tableName: String, row: MutableMap<String, Any?>) {
        val nameColumn = nameColumnByTable[tableName]
        if (!nameColumn.isNullOrBlank()) {
            val raw = row[nameColumn]?.toString().orEmpty()
            if (raw.isNotBlank()) {
                row[nameColumn] = normalizeDisplayName(raw)
            }
        }

        if (tableName == FusionDatabaseSchema.TABLE_TAG_ALIASES) {
            val alias = row["alias_value"]?.toString().orEmpty()
            if (alias.isNotBlank()) {
                row["alias_value"] = normalizeDisplayName(alias)
            }
        }
    }

    private fun normalizePathFields(row: MutableMap<String, Any?>) {
        row.keys.toList().forEach { key ->
            if (!key.contains("uri", ignoreCase = true) && !key.contains("path", ignoreCase = true)) {
                return@forEach
            }
            val value = row[key]?.toString().orEmpty()
            if (value.isBlank()) {
                return@forEach
            }
            row[key] = normalizePath(value)
        }
    }

    private fun normalizeValue(column: ColumnSchema, value: Any?): Any? {
        if (value == null) {
            return null
        }

        val text = value.toString().trim()
        if (text.isEmpty() || text.equals("null", ignoreCase = true) || text.equals("none", ignoreCase = true)) {
            return null
        }

        val name = column.name.lowercase(Locale.US)
        if (name.endsWith("_id") || name.endsWith("_code")) {
            return text
        }

        if (name.endsWith("_at_ms") || name.endsWith("_ms")) {
            return parseDateLike(text)
        }

        return when (column.typeAffinity.uppercase(Locale.US)) {
            "INTEGER" -> {
                val boolLike = parseBooleanLike(text)
                boolLike?.let { if (it) 1L else 0L } ?: text.toLongOrNull()
            }
            "REAL", "FLOAT", "DOUBLE" -> text.toDoubleOrNull()
            else -> {
                if (name == "favorite" || name == "enabled") {
                    val boolLike = parseBooleanLike(text)
                    boolLike?.let { if (it) 1L else 0L } ?: text
                } else {
                    text
                }
            }
        }
    }

    private fun parseDateLike(raw: String): Long? {
        raw.toLongOrNull()?.let { return it }

        val patterns = listOf(
            "yyyy-MM-dd'T'HH:mm:ss.SSSX",
            "yyyy-MM-dd'T'HH:mm:ssX",
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-dd",
        )
        patterns.forEach { pattern ->
            try {
                val parser = SimpleDateFormat(pattern, Locale.US)
                parser.isLenient = false
                val parsed = parser.parse(raw)
                if (parsed != null) {
                    return parsed.time
                }
            } catch (_: ParseException) {
                // Ignore; next parser attempts follow.
            }
        }
        return null
    }

    private fun parseBooleanLike(raw: String): Boolean? {
        return when (raw.lowercase(Locale.US)) {
            "1", "true", "yes", "y", "on" -> true
            "0", "false", "no", "n", "off" -> false
            else -> null
        }
    }

    private fun normalizeDisplayName(raw: String): String {
        val compact = raw.trim().replace(Regex("\\s+"), " ")
        if (compact.isBlank()) {
            return compact
        }

        val allLower = compact == compact.lowercase(Locale.US)
        val allUpper = compact == compact.uppercase(Locale.US)
        if (!allLower && !allUpper) {
            return compact
        }

        return compact.split(' ').joinToString(" ") { segment ->
            if (segment.isBlank()) {
                segment
            } else {
                segment.substring(0, 1).uppercase(Locale.US) + segment.substring(1).lowercase(Locale.US)
            }
        }
    }

    private fun normalizePath(raw: String): String {
        val normalizedSlashes = raw.trim().replace('\\', '/')
        val withoutDuplicate = normalizedSlashes.replace(Regex("/+"), "/")
        return if (withoutDuplicate.length > 8 && withoutDuplicate[1] == ':') {
            val drive = withoutDuplicate.substring(0, 2).uppercase(Locale.US)
            drive + withoutDuplicate.substring(2)
        } else {
            withoutDuplicate
        }
    }

    private fun resolveAliases(
        model: CanonicalImportModel,
        request: ExternalImportRequest,
        warnings: MutableList<String>,
    ) {
        val aliasLookup = buildAliasLookup(request.aliasHints)

        val seriesAliases = aliasLookup["series"].orEmpty()
        val characterAliases = aliasLookup["characters"].orEmpty()
        val artistAliases = aliasLookup["artists"].orEmpty()
        val tagAliases = aliasLookup["tags"].orEmpty()
        val collectionAliases = aliasLookup["collections"].orEmpty()

        model.rowsByTable.forEach { (tableName, rows) ->
            rows.forEachIndexed { index, row ->
                when (tableName) {
                    FusionDatabaseSchema.TABLE_CHARACTERS -> {
                        resolveAliasValue(row, "primary_series_code", listOf("series", "series_name"), seriesAliases)
                    }
                    FusionDatabaseSchema.TABLE_CHARACTER_SERIES,
                    FusionDatabaseSchema.TABLE_IMAGE_SERIES,
                    -> {
                        resolveAliasValue(row, "series_code", listOf("series", "series_name"), seriesAliases)
                    }
                    FusionDatabaseSchema.TABLE_IMAGE_CHARACTERS -> {
                        resolveAliasValue(row, "character_id", listOf("character", "character_name"), characterAliases)
                    }
                    FusionDatabaseSchema.TABLE_IMAGE_ARTISTS -> {
                        resolveAliasValue(row, "artist_id", listOf("artist", "artist_name"), artistAliases)
                    }
                    FusionDatabaseSchema.TABLE_IMAGE_TAGS -> {
                        resolveAliasValue(row, "tag_id", listOf("tag", "tag_name"), tagAliases)
                    }
                    FusionDatabaseSchema.TABLE_COLLECTION_IMAGES -> {
                        resolveAliasValue(row, "collection_id", listOf("collection", "collection_name"), collectionAliases)
                    }
                }

                val idColumn = idColumnByTable[tableName]
                val nameColumn = nameColumnByTable[tableName]
                if (!idColumn.isNullOrBlank() && !nameColumn.isNullOrBlank()) {
                    val id = row[idColumn]?.toString().orEmpty()
                    val name = row[nameColumn]?.toString().orEmpty()
                    if (id.isBlank() && name.isNotBlank()) {
                        val aliasSource = when (tableName) {
                            FusionDatabaseSchema.TABLE_SERIES -> seriesAliases
                            FusionDatabaseSchema.TABLE_CHARACTERS -> characterAliases
                            FusionDatabaseSchema.TABLE_ARTISTS -> artistAliases
                            FusionDatabaseSchema.TABLE_TAGS -> tagAliases
                            FusionDatabaseSchema.TABLE_COLLECTIONS -> collectionAliases
                            else -> emptyMap()
                        }
                        val resolved = aliasSource[name.lowercase(Locale.US)]
                        if (!resolved.isNullOrBlank()) {
                            row[idColumn] = resolved
                        } else {
                            warnings += "$tableName row ${index + 1}: could not resolve alias for name '$name'"
                        }
                    }
                }
            }
        }
    }

    private fun buildAliasLookup(
        aliasHints: Map<String, Map<String, String>>,
    ): Map<String, Map<String, String>> {
        val lookup = mutableMapOf<String, MutableMap<String, String>>()
        listOf("series", "characters", "artists", "tags", "collections").forEach { key ->
            lookup[key] = mutableMapOf()
        }

        val db = database.readableDatabase

        db.rawQuery(
            "SELECT series_code, canonical_title, aliases_json FROM ${FusionDatabaseSchema.TABLE_SERIES}",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0).orEmpty().trim()
                val title = cursor.getString(1).orEmpty().trim()
                if (id.isBlank()) {
                    continue
                }
                if (title.isNotBlank()) {
                    lookup["series"]?.put(title.lowercase(Locale.US), id)
                }
                parseJsonArray(cursor.getString(2)).forEach { alias ->
                    lookup["series"]?.put(alias.lowercase(Locale.US), id)
                }
            }
        }

        db.rawQuery(
            "SELECT character_id, canonical_name, recognition_profile_json FROM ${FusionDatabaseSchema.TABLE_CHARACTERS}",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0).orEmpty().trim()
                val name = cursor.getString(1).orEmpty().trim()
                if (id.isBlank()) {
                    continue
                }
                if (name.isNotBlank()) {
                    lookup["characters"]?.put(name.lowercase(Locale.US), id)
                }
                val profile = cursor.getString(2).orEmpty()
                val aliases = runCatching {
                    val profileJson = JSONObject(profile)
                    val aliasArray = profileJson.optJSONArray("aliases") ?: JSONArray()
                    buildList {
                        for (i in 0 until aliasArray.length()) {
                            val alias = aliasArray.optString(i).trim()
                            if (alias.isNotBlank()) {
                                add(alias)
                            }
                        }
                    }
                }.getOrDefault(emptyList())
                aliases.forEach { alias ->
                    lookup["characters"]?.put(alias.lowercase(Locale.US), id)
                }
            }
        }

        db.rawQuery(
            "SELECT artist_id, display_name, aliases_json FROM ${FusionDatabaseSchema.TABLE_ARTISTS}",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0).orEmpty().trim()
                val name = cursor.getString(1).orEmpty().trim()
                if (id.isBlank()) {
                    continue
                }
                if (name.isNotBlank()) {
                    lookup["artists"]?.put(name.lowercase(Locale.US), id)
                }
                parseJsonArray(cursor.getString(2)).forEach { alias ->
                    lookup["artists"]?.put(alias.lowercase(Locale.US), id)
                }
            }
        }

        db.rawQuery(
            "SELECT tag_id, canonical_name FROM ${FusionDatabaseSchema.TABLE_TAGS}",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0).orEmpty().trim()
                val name = cursor.getString(1).orEmpty().trim()
                if (id.isBlank()) {
                    continue
                }
                if (name.isNotBlank()) {
                    lookup["tags"]?.put(name.lowercase(Locale.US), id)
                }
            }
        }

        db.rawQuery(
            "SELECT tag_id, alias_value FROM ${FusionDatabaseSchema.TABLE_TAG_ALIASES}",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0).orEmpty().trim()
                val alias = cursor.getString(1).orEmpty().trim()
                if (id.isBlank() || alias.isBlank()) {
                    continue
                }
                lookup["tags"]?.put(alias.lowercase(Locale.US), id)
            }
        }

        db.rawQuery(
            "SELECT collection_id, collection_name FROM ${FusionDatabaseSchema.TABLE_COLLECTIONS}",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0).orEmpty().trim()
                val name = cursor.getString(1).orEmpty().trim()
                if (id.isBlank()) {
                    continue
                }
                if (name.isNotBlank()) {
                    lookup["collections"]?.put(name.lowercase(Locale.US), id)
                }
            }
        }

        aliasHints.forEach { (category, mapping) ->
            val bucket = lookup.getOrPut(category.lowercase(Locale.US)) { mutableMapOf() }
            mapping.forEach { (alias, id) ->
                val cleanAlias = alias.trim().lowercase(Locale.US)
                val cleanId = id.trim()
                if (cleanAlias.isNotBlank() && cleanId.isNotBlank()) {
                    bucket[cleanAlias] = cleanId
                }
            }
        }

        return lookup.mapValues { (_, values) -> values.toMap() }
    }

    private fun resolveAliasValue(
        row: MutableMap<String, Any?>,
        idColumn: String,
        fallbackNameColumns: List<String>,
        aliasLookup: Map<String, String>,
    ) {
        val currentId = row[idColumn]?.toString()?.trim().orEmpty()
        if (currentId.isNotBlank()) {
            val direct = aliasLookup[currentId.lowercase(Locale.US)]
            if (!direct.isNullOrBlank()) {
                row[idColumn] = direct
            }
            return
        }

        val fallback = fallbackNameColumns
            .asSequence()
            .mapNotNull { row[it]?.toString()?.trim() }
            .firstOrNull { it.isNotBlank() }
            ?: return

        val resolved = aliasLookup[fallback.lowercase(Locale.US)]
        if (!resolved.isNullOrBlank()) {
            row[idColumn] = resolved
        }
    }

    private fun resolveTaxonomy(model: CanonicalImportModel): List<String> {
        val warnings = mutableListOf<String>()

        val importIds = mutableMapOf<Pair<String, String>, MutableSet<String>>()
        idColumnByTable.forEach { (tableName, idColumn) ->
            val ids = model.rowsByTable[tableName]
                .orEmpty()
                .mapNotNull { it[idColumn]?.toString()?.trim() }
                .filter { it.isNotBlank() }
                .toMutableSet()
            importIds[tableName to idColumn] = ids
        }

        relationRules.forEach { rule ->
            val targetIds = collectIds(rule.targetTable, rule.targetColumn, importIds)
            val rows = model.rowsByTable[rule.tableName].orEmpty()
            rows.forEachIndexed { index, row ->
                val value = row[rule.columnName]?.toString()?.trim().orEmpty()
                if (value.isBlank()) {
                    return@forEachIndexed
                }
                if (!targetIds.contains(value)) {
                    warnings += "${rule.tableName} row ${index + 1}: missing reference ${rule.columnName}=$value"
                }
            }
        }

        model.rowsByTable.forEach { (tableName, rows) ->
            rows.forEachIndexed { index, row ->
                enumRules.filterKeys { it.first == tableName }.forEach { (key, allowedValues) ->
                    val column = key.second
                    val value = row[column]?.toString()?.trim()?.lowercase(Locale.US).orEmpty()
                    if (value.isBlank()) {
                        return@forEach
                    }
                    if (!allowedValues.contains(value)) {
                        warnings += "$tableName row ${index + 1}: invalid enum value $column=$value"
                    }
                }
            }
        }

        return warnings
    }

    private fun collectIds(
        tableName: String,
        columnName: String,
        importIds: Map<Pair<String, String>, MutableSet<String>>,
    ): Set<String> {
        val imported = importIds[tableName to columnName].orEmpty().toMutableSet()
        val sql = "SELECT $columnName FROM $tableName"
        runCatching {
            database.readableDatabase.rawQuery(sql, emptyArray()).use { cursor ->
                while (cursor.moveToNext()) {
                    val id = cursor.getString(0)?.trim().orEmpty()
                    if (id.isNotBlank()) {
                        imported += id
                    }
                }
            }
        }
        return imported
    }

    private fun detectDuplicates(model: CanonicalImportModel): List<ExternalImportDuplicateCandidate> {
        val duplicates = mutableListOf<ExternalImportDuplicateCandidate>()

        val schemas = supportedTables.associateWith { loadTableSchema(it) }
        model.rowsByTable.forEach { (tableName, rows) ->
            val schema = schemas[tableName] ?: return@forEach
            val pkColumns = schema.primaryKeyColumns
            if (pkColumns.isEmpty()) {
                return@forEach
            }

            val seen = mutableSetOf<String>()
            rows.forEach { row ->
                val key = buildPrimaryKeyKey(pkColumns, row)
                if (key.isBlank()) {
                    return@forEach
                }
                if (!seen.add(key)) {
                    duplicates += ExternalImportDuplicateCandidate(
                        duplicateType = "immutable_id_source",
                        tableName = tableName,
                        key = key,
                        importedValue = key,
                        existingValue = null,
                        details = "Duplicate immutable key in imported payload",
                    )
                }

                if (existsByPrimaryKey(tableName, schema, row)) {
                    duplicates += ExternalImportDuplicateCandidate(
                        duplicateType = "immutable_id_existing",
                        tableName = tableName,
                        key = key,
                        importedValue = key,
                        existingValue = key,
                        details = "Immutable key already exists in fusion database",
                    )
                }
            }
        }

        val existingPaths = mutableSetOf<String>()
        database.readableDatabase.rawQuery("SELECT uri FROM images", emptyArray()).use { cursor ->
            while (cursor.moveToNext()) {
                val value = normalizePath(cursor.getString(0).orEmpty())
                if (value.isNotBlank()) {
                    existingPaths += value.lowercase(Locale.US)
                }
            }
        }
        database.readableDatabase.rawQuery(
            "SELECT source_uri FROM ${FusionDatabaseSchema.TABLE_IMAGE_PROFILES}",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val value = normalizePath(cursor.getString(0).orEmpty())
                if (value.isNotBlank()) {
                    existingPaths += value.lowercase(Locale.US)
                }
            }
        }

        val importedPaths = mutableSetOf<String>()
        model.rowsByTable[FusionDatabaseSchema.TABLE_IMAGE_PROFILES].orEmpty().forEach { row ->
            val sourceUri = normalizePath(row["source_uri"]?.toString().orEmpty())
            if (sourceUri.isBlank()) {
                return@forEach
            }
            val normalized = sourceUri.lowercase(Locale.US)
            if (!importedPaths.add(normalized)) {
                duplicates += ExternalImportDuplicateCandidate(
                    duplicateType = "path_source",
                    tableName = FusionDatabaseSchema.TABLE_IMAGE_PROFILES,
                    key = sourceUri,
                    importedValue = sourceUri,
                    existingValue = null,
                    details = "Duplicate path in imported payload",
                )
            }
            if (existingPaths.contains(normalized)) {
                duplicates += ExternalImportDuplicateCandidate(
                    duplicateType = "path_existing",
                    tableName = FusionDatabaseSchema.TABLE_IMAGE_PROFILES,
                    key = sourceUri,
                    importedValue = sourceUri,
                    existingValue = sourceUri,
                    details = "Path already exists in local database",
                )
            }
        }

        val existingHashes = collectExistingHashes()
        val importedHashes = mutableSetOf<String>()
        model.rowsByTable[FusionDatabaseSchema.TABLE_IMAGE_PROFILES].orEmpty().forEach { row ->
            val hash = extractHash(row)
            if (hash.isBlank()) {
                return@forEach
            }
            if (!importedHashes.add(hash)) {
                duplicates += ExternalImportDuplicateCandidate(
                    duplicateType = "hash_source",
                    tableName = FusionDatabaseSchema.TABLE_IMAGE_PROFILES,
                    key = hash,
                    importedValue = hash,
                    existingValue = null,
                    details = "Hash appears multiple times in import payload",
                )
            }
            if (existingHashes.contains(hash)) {
                duplicates += ExternalImportDuplicateCandidate(
                    duplicateType = "hash_existing",
                    tableName = FusionDatabaseSchema.TABLE_IMAGE_PROFILES,
                    key = hash,
                    importedValue = hash,
                    existingValue = hash,
                    details = "Hash already exists in local database",
                )
            }
        }

        val existingIdentity = mutableSetOf<String>()
        database.readableDatabase.rawQuery(
            "SELECT COALESCE(uri, ''), COALESCE(filename, '') FROM images",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val identity = buildImageIdentity(cursor.getString(0).orEmpty(), cursor.getString(1).orEmpty())
                if (identity.isNotBlank()) {
                    existingIdentity += identity
                }
            }
        }

        val importedIdentity = mutableSetOf<String>()
        model.imageSnapshotRows.forEach { row ->
            val identity = buildImageIdentity(
                row["uri"]?.toString().orEmpty(),
                row["filename"]?.toString().orEmpty(),
            )
            if (identity.isBlank()) {
                return@forEach
            }
            if (!importedIdentity.add(identity)) {
                duplicates += ExternalImportDuplicateCandidate(
                    duplicateType = "image_identity_source",
                    tableName = "images_snapshot",
                    key = identity,
                    importedValue = identity,
                    existingValue = null,
                    details = "Image identity duplicated in snapshot payload",
                )
            }
            if (existingIdentity.contains(identity)) {
                duplicates += ExternalImportDuplicateCandidate(
                    duplicateType = "image_identity_existing",
                    tableName = "images_snapshot",
                    key = identity,
                    importedValue = identity,
                    existingValue = identity,
                    details = "Image identity already exists in local database",
                )
            }
        }

        return duplicates
    }

    private data class ConflictResolutionResult(
        val rows: List<ResolvedRow>,
        val conflicts: List<ExternalImportConflict>,
        val warnings: List<String>,
    )

    private fun resolveConflicts(
        model: CanonicalImportModel,
        request: ExternalImportRequest,
        duplicates: List<ExternalImportDuplicateCandidate>,
    ): ConflictResolutionResult {
        val resolvedRows = mutableListOf<ResolvedRow>()
        val conflicts = mutableListOf<ExternalImportConflict>()
        val warnings = mutableListOf<String>()

        val duplicateByTableKey = duplicates.groupBy { "${it.tableName}|${it.key}" }

        FusionDatabaseSchema.DOMAIN_TABLE_ORDER.forEach { tableName ->
            val schema = loadTableSchema(tableName)
            val rows = model.rowsByTable[tableName].orEmpty()
            rows.forEachIndexed { index, row ->
                val key = buildPrimaryKeyKey(schema.primaryKeyColumns, row)
                if (schema.primaryKeyColumns.isNotEmpty() && key.isBlank()) {
                    resolvedRows += ResolvedRow(
                        tableName = tableName,
                        key = "row-${index + 1}",
                        action = MergeAction.SKIP,
                        row = row,
                        reason = "missing primary key",
                    )
                    warnings += "$tableName row ${index + 1}: missing primary key"
                    return@forEachIndexed
                }

                val existingRow = readExistingRowByPrimaryKey(tableName, schema, row)
                if (existingRow == null) {
                    val createRow = row.toMutableMap()
                    val namedConflict = resolveNameConflictForCreate(tableName, createRow, request.conflictStrategy, request.importId)
                    if (namedConflict != null) {
                        conflicts += namedConflict.first
                        if (namedConflict.second == MergeAction.SKIP) {
                            resolvedRows += ResolvedRow(tableName, key, MergeAction.SKIP, createRow, namedConflict.first.decision)
                            return@forEachIndexed
                        }
                    }

                    val pathConflict = resolvePathConflictForCreate(tableName, createRow, request.conflictStrategy, request.importId)
                    if (pathConflict != null) {
                        conflicts += pathConflict
                        if (pathConflict.decision.startsWith("skip")) {
                            resolvedRows += ResolvedRow(tableName, key, MergeAction.SKIP, createRow, pathConflict.decision)
                            return@forEachIndexed
                        }
                    }

                    resolvedRows += ResolvedRow(
                        tableName = tableName,
                        key = key,
                        action = MergeAction.CREATE,
                        row = createRow,
                        reason = "create",
                    )
                    return@forEachIndexed
                }

                if (rowsEquivalent(existingRow, row)) {
                    resolvedRows += ResolvedRow(tableName, key, MergeAction.SKIP, row, "unchanged")
                    return@forEachIndexed
                }

                val duplicateKey = "$tableName|$key"
                val duplicateEntries = duplicateByTableKey[duplicateKey].orEmpty()
                if (duplicateEntries.isNotEmpty()) {
                    val conflict = ExternalImportConflict(
                        tableName = tableName,
                        key = key,
                        reason = "immutable-id conflict",
                        strategy = request.conflictStrategy,
                        decision = "",
                    )
                    when (request.conflictStrategy) {
                        ExternalImportConflictStrategy.SKIP,
                        ExternalImportConflictStrategy.KEEP_BOTH,
                        ExternalImportConflictStrategy.RENAME_IMPORTED,
                        -> {
                            val decision = if (request.conflictStrategy == ExternalImportConflictStrategy.RENAME_IMPORTED) {
                                "skip:rename-imported-not-applicable-to-immutable-id"
                            } else {
                                "skip:keep-existing"
                            }
                            conflicts += conflict.copy(decision = decision)
                            resolvedRows += ResolvedRow(
                                tableName = tableName,
                                key = key,
                                action = MergeAction.SKIP,
                                row = row,
                                reason = decision,
                            )
                        }
                        ExternalImportConflictStrategy.OVERWRITE -> {
                            conflicts += conflict.copy(decision = "overwrite")
                            resolvedRows += ResolvedRow(
                                tableName = tableName,
                                key = key,
                                action = MergeAction.UPDATE,
                                row = row.toMutableMap(),
                                reason = "overwrite",
                            )
                        }
                        ExternalImportConflictStrategy.MERGE_METADATA -> {
                            val merged = mergeRows(existingRow, row)
                            conflicts += conflict.copy(decision = "merge_metadata")
                            resolvedRows += ResolvedRow(
                                tableName = tableName,
                                key = key,
                                action = MergeAction.UPDATE,
                                row = merged,
                                reason = "merge_metadata",
                            )
                        }
                    }
                } else {
                    resolvedRows += ResolvedRow(
                        tableName = tableName,
                        key = key,
                        action = MergeAction.UPDATE,
                        row = row.toMutableMap(),
                        reason = "update",
                    )
                }
            }
        }

        return ConflictResolutionResult(
            rows = resolvedRows,
            conflicts = conflicts,
            warnings = warnings,
        )
    }

    private fun resolveNameConflictForCreate(
        tableName: String,
        row: MutableMap<String, Any?>,
        strategy: ExternalImportConflictStrategy,
        importId: String,
    ): Pair<ExternalImportConflict, MergeAction>? {
        val nameColumn = nameColumnByTable[tableName] ?: return null
        val idColumn = idColumnByTable[tableName] ?: return null
        val displayName = row[nameColumn]?.toString()?.trim().orEmpty()
        if (displayName.isBlank()) {
            return null
        }

        val importIdValue = row[idColumn]?.toString()?.trim().orEmpty()
        val sql = "SELECT $idColumn FROM $tableName WHERE LOWER($nameColumn) = LOWER(?) LIMIT 1"
        val existingId = database.readableDatabase.rawQuery(sql, arrayOf(displayName)).use { cursor ->
            if (!cursor.moveToFirst()) {
                null
            } else {
                cursor.getString(0)?.trim()
            }
        }

        if (existingId.isNullOrBlank() || existingId == importIdValue) {
            return null
        }

        return when (strategy) {
            ExternalImportConflictStrategy.SKIP -> {
                Pair(
                    ExternalImportConflict(
                        tableName = tableName,
                        key = "$nameColumn:$displayName",
                        reason = "name conflict",
                        strategy = strategy,
                        decision = "skip:name-conflict",
                    ),
                    MergeAction.SKIP,
                )
            }
            ExternalImportConflictStrategy.KEEP_BOTH,
            ExternalImportConflictStrategy.RENAME_IMPORTED,
            -> {
                val suffix = importId.take(8)
                row[nameColumn] = "$displayName (Imported $suffix)"
                Pair(
                    ExternalImportConflict(
                        tableName = tableName,
                        key = "$nameColumn:$displayName",
                        reason = "name conflict",
                        strategy = strategy,
                        decision = "rename-imported-name",
                    ),
                    MergeAction.CREATE,
                )
            }
            ExternalImportConflictStrategy.OVERWRITE -> {
                Pair(
                    ExternalImportConflict(
                        tableName = tableName,
                        key = "$nameColumn:$displayName",
                        reason = "name conflict",
                        strategy = strategy,
                        decision = "overwrite-with-different-id",
                    ),
                    MergeAction.CREATE,
                )
            }
            ExternalImportConflictStrategy.MERGE_METADATA -> {
                Pair(
                    ExternalImportConflict(
                        tableName = tableName,
                        key = "$nameColumn:$displayName",
                        reason = "name conflict",
                        strategy = strategy,
                        decision = "skip:merge-metadata-requires-same-id",
                    ),
                    MergeAction.SKIP,
                )
            }
        }
    }

    private fun resolvePathConflictForCreate(
        tableName: String,
        row: MutableMap<String, Any?>,
        strategy: ExternalImportConflictStrategy,
        importId: String,
    ): ExternalImportConflict? {
        if (tableName != FusionDatabaseSchema.TABLE_IMAGE_PROFILES) {
            return null
        }

        val sourceUri = normalizePath(row["source_uri"]?.toString().orEmpty())
        val imageId = row["image_id"]?.toString().orEmpty()
        if (sourceUri.isBlank()) {
            return null
        }

        val existingImageId = database.readableDatabase.rawQuery(
            "SELECT image_id FROM ${FusionDatabaseSchema.TABLE_IMAGE_PROFILES} WHERE source_uri = ? LIMIT 1",
            arrayOf(sourceUri),
        ).use { cursor ->
            if (!cursor.moveToFirst()) {
                null
            } else {
                cursor.getLong(0).toString()
            }
        }

        if (existingImageId.isNullOrBlank() || existingImageId == imageId) {
            return null
        }

        return when (strategy) {
            ExternalImportConflictStrategy.SKIP -> {
                ExternalImportConflict(
                    tableName = tableName,
                    key = sourceUri,
                    reason = "path conflict",
                    strategy = strategy,
                    decision = "skip:path-conflict",
                )
            }
            ExternalImportConflictStrategy.KEEP_BOTH,
            ExternalImportConflictStrategy.RENAME_IMPORTED,
            -> {
                val suffix = importId.take(8)
                row["source_uri"] = "$sourceUri#imported=$suffix"
                ExternalImportConflict(
                    tableName = tableName,
                    key = sourceUri,
                    reason = "path conflict",
                    strategy = strategy,
                    decision = "rename-imported-path",
                )
            }
            ExternalImportConflictStrategy.OVERWRITE -> {
                ExternalImportConflict(
                    tableName = tableName,
                    key = sourceUri,
                    reason = "path conflict",
                    strategy = strategy,
                    decision = "overwrite-path-conflict",
                )
            }
            ExternalImportConflictStrategy.MERGE_METADATA -> {
                ExternalImportConflict(
                    tableName = tableName,
                    key = sourceUri,
                    reason = "path conflict",
                    strategy = strategy,
                    decision = "merge-metadata-path-conflict",
                )
            }
        }
    }

    private fun rowsEquivalent(existing: Map<String, Any?>, incoming: Map<String, Any?>): Boolean {
        val keys = (existing.keys + incoming.keys).toSet()
        return keys.all { key ->
            val left = existing[key]?.toString()?.trim().orEmpty()
            val right = incoming[key]?.toString()?.trim().orEmpty()
            left == right
        }
    }

    private fun mergeRows(existing: Map<String, Any?>, incoming: Map<String, Any?>): MutableMap<String, Any?> {
        val merged = existing.toMutableMap()
        incoming.forEach { (key, value) ->
            if (value == null) {
                return@forEach
            }
            val incomingText = value.toString().trim()
            if (incomingText.isBlank()) {
                return@forEach
            }

            if (key.endsWith("_json")) {
                val combined = mergeJsonStrings(existing[key]?.toString().orEmpty(), incomingText)
                merged[key] = combined
            } else {
                merged[key] = value
            }
        }
        return merged
    }

    private fun mergeJsonStrings(existingJson: String, incomingJson: String): String {
        val existing = runCatching { JSONObject(existingJson) }.getOrNull()
        val incoming = runCatching { JSONObject(incomingJson) }.getOrNull()
        if (existing == null && incoming == null) {
            return incomingJson
        }
        if (existing == null) {
            return incoming?.toString() ?: incomingJson
        }
        if (incoming == null) {
            return existing.toString()
        }

        val keys = incoming.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            existing.put(key, incoming.opt(key))
        }
        return existing.toString()
    }

    private fun validatePreparedImport(
        model: CanonicalImportModel,
        duplicates: List<ExternalImportDuplicateCandidate>,
        conflicts: List<ExternalImportConflict>,
        warnings: List<String>,
    ): FusionValidationReport {
        val issues = mutableListOf<FusionValidationIssue>()

        val duplicateIdCount = duplicates.count { it.duplicateType == "immutable_id_source" }
        if (duplicateIdCount > 0) {
            issues += FusionValidationIssue(
                code = "duplicate_immutable_ids",
                severity = "error",
                count = duplicateIdCount,
                details = "Duplicate immutable IDs detected in import payload",
            )
        }

        val missingRequiredEntityCount = countMissingRequiredEntities(model)
        if (missingRequiredEntityCount > 0) {
            issues += FusionValidationIssue(
                code = "missing_required_entities",
                severity = "error",
                count = missingRequiredEntityCount,
                details = "Required entities or required fields are missing",
            )
        }

        val brokenReferenceCount = countBrokenReferences(model)
        if (brokenReferenceCount > 0) {
            issues += FusionValidationIssue(
                code = "missing_references",
                severity = "error",
                count = brokenReferenceCount,
                details = "Referenced entities are missing from import and local database",
            )
        }

        val invalidEnumCount = countInvalidEnums(model)
        if (invalidEnumCount > 0) {
            issues += FusionValidationIssue(
                code = "invalid_enum_values",
                severity = "error",
                count = invalidEnumCount,
                details = "Import payload contains invalid enum values",
            )
        }

        val relationshipIntegrityCount = countRelationshipIntegrityViolations(model)
        if (relationshipIntegrityCount > 0) {
            issues += FusionValidationIssue(
                code = "relationship_integrity",
                severity = "error",
                count = relationshipIntegrityCount,
                details = "Relationship integrity violations detected in import payload",
            )
        }

        if (conflicts.isNotEmpty()) {
            issues += FusionValidationIssue(
                code = "conflicts_detected",
                severity = "warning",
                count = conflicts.size,
                details = "Conflict resolver produced decisions for merge",
            )
        }

        val currentQuickCheck = DatabaseHealthChecks.quickCheckResult(database.readableDatabase)
        val currentForeignKeyViolations = DatabaseHealthChecks.foreignKeyViolationCount(database.readableDatabase)
        if (currentQuickCheck != "ok") {
            issues += FusionValidationIssue(
                code = "database_quick_check",
                severity = "warning",
                count = 1,
                details = currentQuickCheck,
            )
        }
        if (currentForeignKeyViolations > 0) {
            issues += FusionValidationIssue(
                code = "database_foreign_key_violations",
                severity = "warning",
                count = currentForeignKeyViolations,
                details = "Local database currently has foreign key violations before import",
            )
        }

        val warningOnly = warnings.filter { it.isNotBlank() }
        if (warningOnly.isNotEmpty()) {
            issues += FusionValidationIssue(
                code = "pipeline_warnings",
                severity = "warning",
                count = warningOnly.size,
                details = warningOnly.take(5).joinToString(" | "),
            )
        }

        val hasError = issues.any { it.severity.equals("error", ignoreCase = true) }
        return FusionValidationReport(
            valid = !hasError,
            generatedAtMs = System.currentTimeMillis(),
            quickCheckResult = currentQuickCheck,
            foreignKeyViolationCount = currentForeignKeyViolations,
            duplicateIdCount = duplicateIdCount,
            brokenReferenceCount = brokenReferenceCount,
            missingRequiredEntityCount = missingRequiredEntityCount,
            invalidRelationshipCount = relationshipIntegrityCount + invalidEnumCount,
            issues = issues,
        )
    }

    private fun countMissingRequiredEntities(model: CanonicalImportModel): Int {
        var count = 0
        val requiredColumnsByTable = mapOf(
            FusionDatabaseSchema.TABLE_FRANCHISES to listOf("franchise_id", "display_name", "canonical_slug"),
            FusionDatabaseSchema.TABLE_SERIES to listOf("series_code", "canonical_title"),
            FusionDatabaseSchema.TABLE_CHARACTERS to listOf("character_id", "canonical_name"),
            FusionDatabaseSchema.TABLE_TAGS to listOf("tag_id", "canonical_name"),
            FusionDatabaseSchema.TABLE_OUTFITS to listOf("outfit_id", "canonical_name"),
            FusionDatabaseSchema.TABLE_WEAPONS to listOf("weapon_id", "canonical_name"),
            FusionDatabaseSchema.TABLE_ARTISTS to listOf("artist_id", "display_name"),
            FusionDatabaseSchema.TABLE_COLLECTIONS to listOf("collection_id", "collection_name", "collection_kind"),
        )

        requiredColumnsByTable.forEach { (tableName, requiredColumns) ->
            model.rowsByTable[tableName].orEmpty().forEach { row ->
                requiredColumns.forEach { column ->
                    val value = row[column]?.toString()?.trim().orEmpty()
                    if (value.isBlank()) {
                        count += 1
                    }
                }
            }
        }

        if (model.rowsByTable.isEmpty()) {
            count += 1
        }

        return count
    }

    private fun countBrokenReferences(model: CanonicalImportModel): Int {
        var count = 0
        val importIds = mutableMapOf<Pair<String, String>, MutableSet<String>>()
        idColumnByTable.forEach { (tableName, idColumn) ->
            importIds[tableName to idColumn] = model.rowsByTable[tableName]
                .orEmpty()
                .mapNotNull { it[idColumn]?.toString()?.trim() }
                .filter { it.isNotBlank() }
                .toMutableSet()
        }

        relationRules.forEach { rule ->
            val validSet = collectIds(rule.targetTable, rule.targetColumn, importIds)
            model.rowsByTable[rule.tableName].orEmpty().forEach { row ->
                val value = row[rule.columnName]?.toString()?.trim().orEmpty()
                if (value.isBlank()) {
                    return@forEach
                }
                if (!validSet.contains(value)) {
                    count += 1
                }
            }
        }

        return count
    }

    private fun countInvalidEnums(model: CanonicalImportModel): Int {
        var count = 0
        model.rowsByTable.forEach { (tableName, rows) ->
            rows.forEach { row ->
                enumRules.filterKeys { it.first == tableName }.forEach { (pair, allowed) ->
                    val value = row[pair.second]?.toString()?.trim()?.lowercase(Locale.US).orEmpty()
                    if (value.isBlank()) {
                        return@forEach
                    }
                    if (!allowed.contains(value)) {
                        count += 1
                    }
                }
            }
        }
        return count
    }

    private fun countRelationshipIntegrityViolations(model: CanonicalImportModel): Int {
        var count = 0
        model.rowsByTable[FusionDatabaseSchema.TABLE_FRANCHISES].orEmpty().forEach { row ->
            val id = row["franchise_id"]?.toString()?.trim().orEmpty()
            val parent = row["parent_franchise_id"]?.toString()?.trim().orEmpty()
            if (id.isNotBlank() && parent.isNotBlank() && id == parent) {
                count += 1
            }
        }
        model.rowsByTable[FusionDatabaseSchema.TABLE_SERIES].orEmpty().forEach { row ->
            val id = row["series_code"]?.toString()?.trim().orEmpty()
            val parent = row["parent_series_code"]?.toString()?.trim().orEmpty()
            if (id.isNotBlank() && parent.isNotBlank() && id == parent) {
                count += 1
            }
        }
        model.rowsByTable[FusionDatabaseSchema.TABLE_TAGS].orEmpty().forEach { row ->
            val id = row["tag_id"]?.toString()?.trim().orEmpty()
            val parent = row["parent_tag_id"]?.toString()?.trim().orEmpty()
            if (id.isNotBlank() && parent.isNotBlank() && id == parent) {
                count += 1
            }
        }
        model.rowsByTable[FusionDatabaseSchema.TABLE_COLLECTIONS].orEmpty().forEach { row ->
            val id = row["collection_id"]?.toString()?.trim().orEmpty()
            val parent = row["parent_collection_id"]?.toString()?.trim().orEmpty()
            if (id.isNotBlank() && parent.isNotBlank() && id == parent) {
                count += 1
            }
        }
        model.rowsByTable[FusionDatabaseSchema.TABLE_SERIES_LINKS].orEmpty().forEach { row ->
            val left = row["series_code"]?.toString()?.trim().orEmpty()
            val right = row["related_series_code"]?.toString()?.trim().orEmpty()
            if (left.isNotBlank() && right.isNotBlank() && left == right) {
                count += 1
            }
        }
        return count
    }

    private fun buildPreview(
        request: ExternalImportRequest,
        resolvedRows: List<ResolvedRow>,
        duplicates: List<ExternalImportDuplicateCandidate>,
        conflicts: List<ExternalImportConflict>,
        warnings: List<String>,
    ): ExternalImportPreview {
        val create = resolvedRows.filter { it.action == MergeAction.CREATE }
            .map { ExternalImportObjectDelta(it.tableName, it.key, "create", it.reason) }
        val update = resolvedRows.filter { it.action == MergeAction.UPDATE }
            .map { ExternalImportObjectDelta(it.tableName, it.key, "update", it.reason) }
        val skip = resolvedRows.filter { it.action == MergeAction.SKIP }
            .map { ExternalImportObjectDelta(it.tableName, it.key, "skip", it.reason) }

        val touchedTables = resolvedRows.map { it.tableName }.toSet().size
        val summary = mapOf(
            "touched_tables" to touchedTables,
            "total_rows" to resolvedRows.size,
            "create_count" to create.size,
            "update_count" to update.size,
            "skip_count" to skip.size,
            "duplicate_count" to duplicates.size,
            "conflict_count" to conflicts.size,
            "warning_count" to warnings.size,
        )

        return ExternalImportPreview(
            importId = request.importId,
            sourceType = request.sourceType,
            replaceExisting = request.replaceExisting,
            objectsToCreate = create,
            objectsToUpdate = update,
            objectsToSkip = skip,
            duplicates = duplicates,
            conflicts = conflicts,
            warnings = warnings.distinct(),
            summaryStatistics = summary,
        )
    }

    private fun emptyPreview(request: ExternalImportRequest): ExternalImportPreview {
        return ExternalImportPreview(
            importId = request.importId,
            sourceType = request.sourceType,
            replaceExisting = request.replaceExisting,
            objectsToCreate = emptyList(),
            objectsToUpdate = emptyList(),
            objectsToSkip = emptyList(),
            duplicates = emptyList(),
            conflicts = emptyList(),
            warnings = emptyList(),
            summaryStatistics = mapOf(
                "touched_tables" to 0,
                "total_rows" to 0,
                "create_count" to 0,
                "update_count" to 0,
                "skip_count" to 0,
                "duplicate_count" to 0,
                "conflict_count" to 0,
                "warning_count" to 0,
            ),
        )
    }

    private fun emptyValidationReport(reason: String): FusionValidationReport {
        return FusionValidationReport(
            valid = false,
            generatedAtMs = System.currentTimeMillis(),
            quickCheckResult = reason,
            foreignKeyViolationCount = 0,
            duplicateIdCount = 0,
            brokenReferenceCount = 0,
            missingRequiredEntityCount = 0,
            invalidRelationshipCount = 0,
            issues = listOf(
                FusionValidationIssue(
                    code = "pipeline_state",
                    severity = "error",
                    count = 1,
                    details = reason,
                ),
            ),
        )
    }

    private fun readSourceContent(source: String): String {
        val trimmed = source.trim()
        if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
            return source
        }
        val file = File(trimmed)
        require(file.exists()) { "Source file not found: $trimmed" }
        return file.readText()
    }

    private fun sourceLabel(source: String): String {
        val trimmed = source.trim()
        return if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
            "inline"
        } else {
            File(trimmed).absolutePath
        }
    }

    private fun resolveTableName(name: String?): String? {
        if (name.isNullOrBlank()) {
            return null
        }
        val normalized = name.trim().lowercase(Locale.US)
        return tableNamesByLower[normalized]
    }

    private fun resolveWorkbookSheet(name: String?): String? {
        if (name.isNullOrBlank()) {
            return null
        }
        return sheetToTableLookup[name.trim().lowercase(Locale.US)]
    }

    private fun parseCsv(content: String): List<List<String>> {
        val rows = mutableListOf<List<String>>()
        val currentRow = mutableListOf<String>()
        val currentField = StringBuilder()
        var inQuotes = false
        var index = 0
        while (index < content.length) {
            val ch = content[index]
            when (ch) {
                '"' -> {
                    if (inQuotes && index + 1 < content.length && content[index + 1] == '"') {
                        currentField.append('"')
                        index += 1
                    } else {
                        inQuotes = !inQuotes
                    }
                }
                ',' -> {
                    if (inQuotes) {
                        currentField.append(ch)
                    } else {
                        currentRow += currentField.toString()
                        currentField.clear()
                    }
                }
                '\n' -> {
                    if (inQuotes) {
                        currentField.append(ch)
                    } else {
                        currentRow += currentField.toString()
                        currentField.clear()
                        rows += currentRow.toList()
                        currentRow.clear()
                    }
                }
                '\r' -> {
                    if (inQuotes) {
                        currentField.append(ch)
                    }
                }
                else -> currentField.append(ch)
            }
            index += 1
        }

        if (currentField.isNotEmpty() || currentRow.isNotEmpty()) {
            currentRow += currentField.toString()
            rows += currentRow.toList()
        }

        return rows
    }

    private fun findCaseInsensitive(map: Map<String, Any?>, key: String): Any? {
        map[key]?.let { return it }
        val target = key.lowercase(Locale.US)
        val foundKey = map.keys.firstOrNull { it.lowercase(Locale.US) == target } ?: return null
        return map[foundKey]
    }

    private fun parseJsonArray(raw: String?): List<String> {
        if (raw.isNullOrBlank()) {
            return emptyList()
        }
        return runCatching {
            val array = JSONArray(raw)
            buildList {
                for (index in 0 until array.length()) {
                    val value = array.optString(index).trim()
                    if (value.isNotBlank()) {
                        add(value)
                    }
                }
            }
        }.getOrDefault(emptyList())
    }

    private fun loadTableSchema(tableName: String): TableSchema {
        val columns = mutableListOf<ColumnSchema>()
        database.readableDatabase.rawQuery("PRAGMA table_info($tableName)", null).use { cursor ->
            while (cursor.moveToNext()) {
                val columnName = cursor.getString(cursor.getColumnIndexOrThrow("name"))
                val type = cursor.getString(cursor.getColumnIndexOrThrow("type")) ?: "TEXT"
                val notNull = cursor.getInt(cursor.getColumnIndexOrThrow("notnull")) == 1
                val defaultValue = if (cursor.isNull(cursor.getColumnIndexOrThrow("dflt_value"))) {
                    null
                } else {
                    cursor.getString(cursor.getColumnIndexOrThrow("dflt_value"))
                }
                val pk = cursor.getInt(cursor.getColumnIndexOrThrow("pk"))
                columns += ColumnSchema(
                    name = columnName,
                    typeAffinity = type,
                    notNull = notNull,
                    defaultValue = defaultValue,
                    pkPosition = pk,
                )
            }
        }

        val primaryColumns = columns
            .filter { it.pkPosition > 0 }
            .sortedBy { it.pkPosition }
            .map { it.name }

        return TableSchema(
            tableName = tableName,
            columns = columns,
            primaryKeyColumns = primaryColumns,
        )
    }

    private fun buildPrimaryKeyKey(pkColumns: List<String>, row: Map<String, Any?>): String {
        if (pkColumns.isEmpty()) {
            return ""
        }
        val values = pkColumns.map { column ->
            row[column]?.toString()?.trim().orEmpty()
        }
        if (values.any { it.isBlank() }) {
            return ""
        }
        return values.joinToString("|")
    }

    private fun existsByPrimaryKey(tableName: String, schema: TableSchema, row: Map<String, Any?>): Boolean {
        if (schema.primaryKeyColumns.isEmpty()) {
            return false
        }
        val keyParts = schema.primaryKeyColumns.map { row[it]?.toString()?.trim().orEmpty() }
        if (keyParts.any { it.isBlank() }) {
            return false
        }
        val where = schema.primaryKeyColumns.joinToString(" AND ") { "$it = ?" }
        val sql = "SELECT 1 FROM $tableName WHERE $where LIMIT 1"
        database.readableDatabase.rawQuery(sql, keyParts.toTypedArray()).use { cursor ->
            return cursor.moveToFirst()
        }
    }

    private fun readExistingRowByPrimaryKey(
        tableName: String,
        schema: TableSchema,
        row: Map<String, Any?>,
    ): Map<String, Any?>? {
        if (schema.primaryKeyColumns.isEmpty()) {
            return null
        }
        val keyParts = schema.primaryKeyColumns.map { row[it]?.toString()?.trim().orEmpty() }
        if (keyParts.any { it.isBlank() }) {
            return null
        }
        val where = schema.primaryKeyColumns.joinToString(" AND ") { "$it = ?" }
        val sql = "SELECT * FROM $tableName WHERE $where LIMIT 1"
        database.readableDatabase.rawQuery(sql, keyParts.toTypedArray()).use { cursor ->
            if (!cursor.moveToFirst()) {
                return null
            }
            val result = mutableMapOf<String, Any?>()
            for (index in 0 until cursor.columnCount) {
                val name = cursor.getColumnName(index)
                val value = if (cursor.isNull(index)) {
                    null
                } else {
                    when (cursor.getType(index)) {
                        Cursor.FIELD_TYPE_INTEGER -> cursor.getLong(index)
                        Cursor.FIELD_TYPE_FLOAT -> cursor.getDouble(index)
                        else -> cursor.getString(index)
                    }
                }
                result[name] = value
            }
            return result
        }
    }

    private fun buildUpsertSql(tableName: String, columns: List<String>): String {
        val columnSql = columns.joinToString(",")
        val placeholders = columns.joinToString(",") { "?" }
        return "INSERT OR REPLACE INTO $tableName($columnSql) VALUES ($placeholders)"
    }

    private fun bindSqlValue(statement: android.database.sqlite.SQLiteStatement, index: Int, value: Any?) {
        when (value) {
            null -> statement.bindNull(index)
            is Int -> statement.bindLong(index, value.toLong())
            is Long -> statement.bindLong(index, value)
            is Float -> statement.bindDouble(index, value.toDouble())
            is Double -> statement.bindDouble(index, value)
            is Boolean -> statement.bindLong(index, if (value) 1L else 0L)
            else -> statement.bindString(index, value.toString())
        }
    }

    private fun clearFusionTables(db: SQLiteDatabase) {
        FusionDatabaseSchema.DOMAIN_TABLE_ORDER.asReversed().forEach { tableName ->
            db.delete(tableName, null, null)
        }
    }

    private fun checkCancellation(importId: String) {
        if (cancelFlags[importId] == true) {
            throw ImportCancelledException("Import cancelled: $importId")
        }
    }

    private fun emitProgress(
        callback: ExternalImportProgressCallback?,
        importId: String,
        stage: String,
        progress: Double,
        message: String,
        processed: Int = 0,
        total: Int = 0,
        startedAtMs: Long = 0L,
    ) {
        callback?.invoke(
            mapOf(
                "import_id" to importId,
                "stage" to stage,
                "progress" to progress.coerceIn(0.0, 1.0),
                "message" to message,
                "processed" to processed,
                "total" to total,
                "started_at_ms" to startedAtMs,
                "updated_at_ms" to System.currentTimeMillis(),
            ),
        )
    }

    private fun exportFusionSnapshotJson(pretty: Boolean): String {
        val root = JSONObject()
        root.put("format", SNAPSHOT_FORMAT)
        root.put("fusion_schema_version", FusionDatabaseSchema.FUSION_SCHEMA_VERSION)
        root.put("generated_at_ms", System.currentTimeMillis())

        val tables = JSONObject()
        FusionDatabaseSchema.DOMAIN_TABLE_ORDER.forEach { tableName ->
            val array = JSONArray()
            database.readableDatabase.rawQuery("SELECT * FROM $tableName", emptyArray()).use { cursor ->
                while (cursor.moveToNext()) {
                    val row = JSONObject()
                    for (index in 0 until cursor.columnCount) {
                        val key = cursor.getColumnName(index)
                        if (cursor.isNull(index)) {
                            row.put(key, JSONObject.NULL)
                        } else {
                            when (cursor.getType(index)) {
                                Cursor.FIELD_TYPE_INTEGER -> row.put(key, cursor.getLong(index))
                                Cursor.FIELD_TYPE_FLOAT -> row.put(key, cursor.getDouble(index))
                                else -> row.put(key, cursor.getString(index))
                            }
                        }
                    }
                    array.put(row)
                }
            }
            tables.put(tableName, array)
        }

        val imageSnapshot = JSONArray()
        database.readableDatabase.rawQuery(
            "SELECT image_id, uri, filename, folder_uri, metadata_text FROM images",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val row = JSONObject()
                row.put("image_id", cursor.getInt(0))
                row.put("uri", cursor.getString(1))
                row.put("filename", cursor.getString(2))
                row.put("folder_uri", cursor.getString(3))
                row.put("metadata_text", cursor.getString(4) ?: "")
                imageSnapshot.put(row)
            }
        }

        root.put("tables", tables)
        root.put("images_snapshot", imageSnapshot)
        return if (pretty) root.toString(2) else root.toString()
    }

    private fun recordImportRunStart(
        request: ExternalImportRequest,
        startedAtMs: Long,
        beforeSnapshotJson: String,
    ) {
        database.writableDatabase.execSQL(
            """
            INSERT OR REPLACE INTO ${FusionDatabaseSchema.TABLE_IMPORT_RUNS}(
                import_id,
                started_at_ms,
                finished_at_ms,
                status,
                source_type,
                conflict_strategy,
                replace_existing,
                summary_json,
                before_snapshot_json,
                after_snapshot_json,
                error_message
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, '{}', ?, NULL, '')
            """.trimIndent(),
            arrayOf(
                request.importId,
                startedAtMs,
                "running",
                request.sourceType.name.lowercase(),
                request.conflictStrategy.name.lowercase(),
                if (request.replaceExisting) 1 else 0,
                beforeSnapshotJson,
            ),
        )
    }

    private fun recordImportRunFinish(
        importId: String,
        status: String,
        finishedAtMs: Long,
        summaryJson: String,
        afterSnapshotJson: String,
        errorMessage: String,
    ) {
        database.writableDatabase.execSQL(
            """
            UPDATE ${FusionDatabaseSchema.TABLE_IMPORT_RUNS}
            SET finished_at_ms = ?,
                status = ?,
                summary_json = ?,
                after_snapshot_json = ?,
                error_message = ?
            WHERE import_id = ?
            """.trimIndent(),
            arrayOf(
                finishedAtMs,
                status,
                summaryJson,
                afterSnapshotJson,
                errorMessage,
                importId,
            ),
        )
    }

    private fun findRollbackCandidate(importId: String?): RollbackCandidate? {
        val sql: String
        val args: Array<String>
        if (importId.isNullOrBlank()) {
            sql = """
                SELECT import_id, before_snapshot_json
                FROM ${FusionDatabaseSchema.TABLE_IMPORT_RUNS}
                WHERE status = 'completed'
                ORDER BY started_at_ms DESC
                LIMIT 1
            """.trimIndent()
            args = emptyArray()
        } else {
            sql = """
                SELECT import_id, before_snapshot_json
                FROM ${FusionDatabaseSchema.TABLE_IMPORT_RUNS}
                WHERE import_id = ?
                LIMIT 1
            """.trimIndent()
            args = arrayOf(importId.trim())
        }

        database.readableDatabase.rawQuery(sql, args).use { cursor ->
            if (!cursor.moveToFirst()) {
                return null
            }
            val id = cursor.getString(0).orEmpty()
            val snapshot = cursor.getString(1).orEmpty()
            if (id.isBlank() || snapshot.isBlank()) {
                return null
            }
            return RollbackCandidate(id, snapshot)
        }
    }

    private fun markRolledBack(originalImportId: String, rollbackImportId: String) {
        val summary = database.readableDatabase.rawQuery(
            "SELECT summary_json FROM ${FusionDatabaseSchema.TABLE_IMPORT_RUNS} WHERE import_id = ? LIMIT 1",
            arrayOf(originalImportId),
        ).use { cursor ->
            if (!cursor.moveToFirst()) {
                "{}"
            } else {
                cursor.getString(0).orEmpty().ifBlank { "{}" }
            }
        }

        val summaryJson = runCatching { JSONObject(summary) }.getOrElse { JSONObject() }
        summaryJson.put("rolled_back", true)
        summaryJson.put("rolled_back_by", rollbackImportId)
        summaryJson.put("rolled_back_at_ms", System.currentTimeMillis())

        database.writableDatabase.execSQL(
            """
            UPDATE ${FusionDatabaseSchema.TABLE_IMPORT_RUNS}
            SET status = ?, summary_json = ?
            WHERE import_id = ?
            """.trimIndent(),
            arrayOf("rolled_back", summaryJson.toString(), originalImportId),
        )
    }

    private fun collectExistingHashes(): Set<String> {
        val hashes = mutableSetOf<String>()
        val regex = Regex("[a-fA-F0-9]{32,64}")

        database.readableDatabase.rawQuery(
            "SELECT metadata_json FROM ${FusionDatabaseSchema.TABLE_IMAGE_PROFILES}",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val metadata = cursor.getString(0).orEmpty()
                regex.findAll(metadata).forEach { match ->
                    hashes += match.value.lowercase(Locale.US)
                }
            }
        }

        database.readableDatabase.rawQuery(
            "SELECT metadata_text FROM images",
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val metadata = cursor.getString(0).orEmpty()
                regex.findAll(metadata).forEach { match ->
                    hashes += match.value.lowercase(Locale.US)
                }
            }
        }

        return hashes
    }

    private fun extractHash(row: Map<String, Any?>): String {
        val metadataJson = row["metadata_json"]?.toString().orEmpty()
        if (metadataJson.isNotBlank()) {
            runCatching {
                val json = JSONObject(metadataJson)
                val keys = listOf("sha256", "hash", "image_hash", "md5")
                keys.forEach { key ->
                    val value = json.optString(key).trim().lowercase(Locale.US)
                    if (value.matches(Regex("[a-f0-9]{16,128}"))) {
                        return value
                    }
                }
            }
        }

        val metadataText = row["metadata_text"]?.toString().orEmpty()
        val match = Regex("[a-fA-F0-9]{32,64}").find(metadataText)
        return match?.value?.lowercase(Locale.US).orEmpty()
    }

    private fun buildImageIdentity(uri: String, filename: String): String {
        val normalizedUri = normalizePath(uri).lowercase(Locale.US)
        val normalizedName = filename.trim().lowercase(Locale.US)
        if (normalizedUri.isBlank() && normalizedName.isBlank()) {
            return ""
        }
        return "$normalizedUri|$normalizedName"
    }
}
