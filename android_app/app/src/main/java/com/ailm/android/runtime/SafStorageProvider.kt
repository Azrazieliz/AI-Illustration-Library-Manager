package com.ailm.android.runtime

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import java.io.InputStream

class SafStorageProvider(
    context: Context,
) : StorageProvider {

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
                val children = node.listFiles()
                for (child in children.asReversed()) {
                    stack.add(child to node.uri.toString())
                }
            }
        }
    }

    override fun openInputStream(uri: String): InputStream? {
        return resolver.openInputStream(Uri.parse(uri))
    }

    override fun exists(uri: String): Boolean {
        val document = DocumentFile.fromSingleUri(appContext, Uri.parse(uri))
        if (document != null) {
            return document.exists()
        }
        val treeDocument = DocumentFile.fromTreeUri(appContext, Uri.parse(uri))
        return treeDocument?.exists() == true
    }
}
