package com.ailm.android.runtime

import android.net.Uri

object FolderUriUtils {
    fun displayName(uri: String): String {
        val normalized = uri.trim().trimEnd('/')
        if (normalized.isBlank()) {
            return ""
        }
        val decoded = Uri.decode(normalized)
        val segment = decoded.substringAfterLast('/').substringAfterLast(':').substringBefore('?').substringBefore('#').trim()
        return segment.ifBlank { "" }
    }
}