package com.ailm.android.runtime

import android.database.sqlite.SQLiteDatabase

object DatabaseHealthChecks {
    fun quickCheckResult(db: SQLiteDatabase): String {
        return db.rawQuery("PRAGMA quick_check(1)", emptyArray()).use { cursor ->
            if (cursor.moveToFirst()) {
                cursor.getString(0) ?: "unknown"
            } else {
                "unknown"
            }
        }
    }

    fun foreignKeyViolationCount(db: SQLiteDatabase): Int {
        return db.rawQuery("PRAGMA foreign_key_check", emptyArray()).use { cursor ->
            var count = 0
            while (cursor.moveToNext()) {
                count += 1
            }
            count
        }
    }
}