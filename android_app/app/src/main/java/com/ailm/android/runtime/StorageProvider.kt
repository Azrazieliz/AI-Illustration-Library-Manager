package com.ailm.android.runtime

import java.io.InputStream

data class StorageNode(
    val uri: String,
    val name: String,
    val isDirectory: Boolean,
    val sizeBytes: Long?,
    val lastModifiedMs: Long?,
    val parentUri: String?,
)

interface StorageProvider {
    fun walkTree(rootUri: String): Sequence<StorageNode>
    fun openInputStream(uri: String): InputStream?
    fun exists(uri: String): Boolean
}
