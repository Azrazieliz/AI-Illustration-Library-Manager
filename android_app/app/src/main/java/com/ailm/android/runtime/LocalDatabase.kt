package com.ailm.android.runtime

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

class LocalDatabase(
    context: Context,
) : SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE images (
                image_id INTEGER PRIMARY KEY AUTOINCREMENT,
                uri TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                parent_uri TEXT,
                size_bytes INTEGER,
                last_modified_ms INTEGER,
                scanned_at_ms INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX idx_images_filename ON images(filename)")
        db.execSQL("CREATE INDEX idx_images_parent_uri ON images(parent_uri)")
        db.execSQL(
            """
            CREATE TABLE review_items (
                review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_uri TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                reason TEXT,
                last_updated_ms INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX idx_review_status ON review_items(status)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            db.execSQL("CREATE INDEX IF NOT EXISTS idx_images_parent_uri ON images(parent_uri)")
        }
        if (oldVersion < 3) {
            db.execSQL(
                """
                CREATE TABLE IF NOT EXISTS review_items (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_uri TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT,
                    last_updated_ms INTEGER NOT NULL
                )
                """.trimIndent(),
            )
            db.execSQL("CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status)")
        }
    }

    companion object {
        private const val DB_NAME = "ailm_android.sqlite"
        private const val DB_VERSION = 3
    }
}
