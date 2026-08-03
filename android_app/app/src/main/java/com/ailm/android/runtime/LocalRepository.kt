package com.ailm.android.runtime

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase

class LocalRepository(
    private val database: LocalDatabase,
) {

    fun upsertImage(node: StorageNode, scannedAtMs: Long) {
        if (node.isDirectory) {
            return
        }
        val values = ContentValues().apply {
            put("uri", node.uri)
            put("filename", node.name)
            put("parent_uri", node.parentUri)
            put("size_bytes", node.sizeBytes)
            put("last_modified_ms", node.lastModifiedMs)
            put("scanned_at_ms", scannedAtMs)
        }
        database.writableDatabase.insertWithOnConflict(
            "images",
            null,
            values,
            SQLiteDatabase.CONFLICT_REPLACE,
        )
        val reviewValues = ContentValues().apply {
            put("image_uri", node.uri)
            put("status", "pending")
            put("reason", "Discovered during scan")
            put("last_updated_ms", scannedAtMs)
        }
        database.writableDatabase.insertWithOnConflict(
            "review_items",
            null,
            reviewValues,
            SQLiteDatabase.CONFLICT_IGNORE,
        )
    }

    fun listImages(query: String?, page: Int, pageSize: Int): List<Map<String, Any>> {
        val normalizedPage = if (page < 1) 1 else page
        val normalizedSize = if (pageSize < 1) 1 else pageSize
        val offset = (normalizedPage - 1) * normalizedSize

        val where = if (query.isNullOrBlank()) "" else "WHERE LOWER(filename) LIKE ? OR LOWER(uri) LIKE ?"
        val args = if (query.isNullOrBlank()) {
            emptyArray()
        } else {
            val term = "%${query.trim().lowercase()}%"
            arrayOf(term, term)
        }

        val sql = """
            SELECT image_id, uri, filename, parent_uri, size_bytes, last_modified_ms
            FROM images
            $where
            ORDER BY filename COLLATE NOCASE ASC, image_id ASC
            LIMIT ? OFFSET ?
        """.trimIndent()

        val finalArgs = args + arrayOf(normalizedSize.toString(), offset.toString())
        val rows = mutableListOf<Map<String, Any>>()
        database.readableDatabase.rawQuery(sql, finalArgs).use { cursor ->
            val imageIdCol = cursor.getColumnIndexOrThrow("image_id")
            val uriCol = cursor.getColumnIndexOrThrow("uri")
            val filenameCol = cursor.getColumnIndexOrThrow("filename")
            val parentCol = cursor.getColumnIndexOrThrow("parent_uri")
            val sizeCol = cursor.getColumnIndexOrThrow("size_bytes")
            val modifiedCol = cursor.getColumnIndexOrThrow("last_modified_ms")
            while (cursor.moveToNext()) {
                val uri = cursor.getString(uriCol)
                val metadata = linkedMapOf<String, Any>()
                metadata["parent_uri"] = cursor.getString(parentCol) ?: ""
                if (!cursor.isNull(sizeCol)) {
                    metadata["size_bytes"] = cursor.getLong(sizeCol)
                }
                if (!cursor.isNull(modifiedCol)) {
                    metadata["last_modified_ms"] = cursor.getLong(modifiedCol)
                }
                rows += linkedMapOf(
                    "image_id" to cursor.getLong(imageIdCol).toInt(),
                    "path" to uri,
                    "filename" to cursor.getString(filenameCol),
                    "thumbnail_url" to uri,
                    "file_url" to uri,
                    "metadata" to metadata,
                )
            }
        }
        return rows
    }

    fun statistics(): Map<String, Any> {
        val sql = "SELECT COUNT(*) AS total_images, COALESCE(SUM(size_bytes), 0) AS total_size_bytes FROM images"
        database.readableDatabase.rawQuery(sql, emptyArray()).use { cursor ->
            if (!cursor.moveToFirst()) {
                return mapOf("total_images" to 0, "total_size_bytes" to 0L)
            }
            return mapOf(
                "total_images" to cursor.getInt(0),
                "total_size_bytes" to cursor.getLong(1),
            )
        }
    }

    fun collections(page: Int, pageSize: Int): List<Map<String, Any>> {
        val normalizedPage = if (page < 1) 1 else page
        val normalizedSize = if (pageSize < 1) 1 else pageSize
        val offset = (normalizedPage - 1) * normalizedSize
        val rows = mutableListOf<Map<String, Any>>()
        val sql = """
            SELECT COALESCE(parent_uri, '') AS parent_uri, COUNT(*) AS image_count
            FROM images
            GROUP BY parent_uri
            ORDER BY parent_uri ASC
            LIMIT ? OFFSET ?
        """.trimIndent()
        database.readableDatabase.rawQuery(sql, arrayOf(normalizedSize.toString(), offset.toString())).use { cursor ->
            while (cursor.moveToNext()) {
                val parentUri = cursor.getString(0)
                rows += mapOf(
                    "collection_id" to parentUri.hashCode(),
                    "name" to if (parentUri.isBlank()) "(root)" else parentUri,
                    "kind" to "dynamic",
                    "image_count" to cursor.getInt(1),
                    "metadata" to mapOf("parent_uri" to parentUri),
                )
            }
        }
        return rows
    }

    fun reviewQueue(limit: Int = 250): List<Map<String, Any>> {
        val rows = mutableListOf<Map<String, Any>>()
        val sql = """
            SELECT review_id, image_uri, status, reason, last_updated_ms
            FROM review_items
            WHERE status = 'pending'
            ORDER BY last_updated_ms DESC, review_id DESC
            LIMIT ?
        """.trimIndent()
        database.readableDatabase.rawQuery(sql, arrayOf(limit.toString())).use { cursor ->
            while (cursor.moveToNext()) {
                rows += mapOf(
                    "id" to cursor.getLong(0).toString(),
                    "item_id" to cursor.getLong(0).toString(),
                    "path" to cursor.getString(1),
                    "status" to cursor.getString(2),
                    "reason" to (cursor.getString(3) ?: ""),
                    "updated_at_ms" to cursor.getLong(4),
                )
            }
        }
        return rows
    }

    fun updateReview(itemId: String, action: String, reason: String?): Boolean {
        val id = itemId.toLongOrNull() ?: return false
        val status = when (action.lowercase()) {
            "approve" -> "approved"
            "reject" -> "rejected"
            "skip" -> "skipped"
            else -> return false
        }
        val values = ContentValues().apply {
            put("status", status)
            put("reason", reason ?: "")
            put("last_updated_ms", System.currentTimeMillis())
        }
        val count = database.writableDatabase.update(
            "review_items",
            values,
            "review_id = ?",
            arrayOf(id.toString()),
        )
        return count > 0
    }

    fun undoLastReviewUpdate(): Boolean {
        val sql = """
            SELECT review_id
            FROM review_items
            WHERE status != 'pending'
            ORDER BY last_updated_ms DESC, review_id DESC
            LIMIT 1
        """.trimIndent()
        val id = database.readableDatabase.rawQuery(sql, emptyArray()).use { cursor ->
            if (!cursor.moveToFirst()) {
                return false
            }
            cursor.getLong(0)
        }
        val values = ContentValues().apply {
            put("status", "pending")
            put("reason", "")
            put("last_updated_ms", System.currentTimeMillis())
        }
        val count = database.writableDatabase.update(
            "review_items",
            values,
            "review_id = ?",
            arrayOf(id.toString()),
        )
        return count > 0
    }
}
