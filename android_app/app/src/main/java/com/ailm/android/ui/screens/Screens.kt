@file:OptIn(
    androidx.compose.foundation.layout.ExperimentalLayoutApi::class,
    androidx.compose.foundation.ExperimentalFoundationApi::class,
)

package com.ailm.android.ui.screens

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.ImageLoader
import coil.compose.AsyncImage
import coil.decode.GifDecoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import com.ailm.android.ui.navigation.AppDestination
import com.ailm.android.ui.viewmodel.AppUiState
import com.ailm.android.ui.viewmodel.AppViewModel
import kotlinx.coroutines.delay
import kotlin.math.max
import kotlin.math.roundToInt

private const val PREFS_NAME = "ailm_android"
private const val PREF_LIBRARY_TREE_URI = "library_tree_uri"
private const val SAF_PERMISSION_TAG = "AilmSafPermission"
private const val UI_TRACE_TAG = "AilmTraceUI"

@Composable
fun ScreenScaffold(
    destination: AppDestination,
    onNavigate: (AppDestination) -> Unit,
    appViewModel: AppViewModel,
) {
    val state by appViewModel.uiState.collectAsState()
    val context = LocalContext.current
    val prefs = remember(context) {
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }

    val folderPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocumentTree(),
    ) { uri ->
        if (uri != null) {
            val uriText = uri.toString()
            val persisted = persistAndVerifyTreePermission(context, uri)
            if (persisted) {
                prefs.edit().putString(PREF_LIBRARY_TREE_URI, uriText).apply()
                appViewModel.setLibraryUri(uriText)
            } else {
                prefs.edit().remove(PREF_LIBRARY_TREE_URI).apply()
                appViewModel.setLibraryUri("")
            }
            appViewModel.refreshDashboard()
        }
    }

    val folderManagerAddLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocumentTree(),
    ) { uri ->
        if (uri != null) {
            val persisted = persistAndVerifyTreePermission(context, uri)
            if (persisted) {
                val uriText = uri.toString()
                appViewModel.setLibraryUri(uriText)
                appViewModel.addLibraryFolder(uriText)
            }
        }
    }

    LaunchedEffect(Unit) {
        val persistedUri = prefs.getString(PREF_LIBRARY_TREE_URI, null).orEmpty()
        val restoredUri = if (persistedUri.isNotBlank() && hasPersistedTreePermission(context, persistedUri)) {
            persistedUri
        } else {
            if (persistedUri.isNotBlank()) {
                Log.w(SAF_PERMISSION_TAG, "Clearing stale SAF URI with missing persisted permission: $persistedUri")
                prefs.edit().remove(PREF_LIBRARY_TREE_URI).apply()
            }
            ""
        }
        appViewModel.initializeConfiguration(restoredUri)
        appViewModel.refreshDashboard()
        appViewModel.refreshScanStatus()
    }

    val chooseFolder: () -> Unit = { folderPickerLauncher.launch(null) }
    val addFolderToManager: () -> Unit = { folderManagerAddLauncher.launch(null) }

    when (destination) {
        AppDestination.Splash -> SplashScreen(
            state = state,
            onNavigate = onNavigate,
        )

        AppDestination.FirstLaunchWizard -> FirstLaunchScreen(
            state = state,
            onChooseFolder = chooseFolder,
            onStartScan = appViewModel::startScan,
            onPauseScan = appViewModel::pauseScan,
            onResumeScan = appViewModel::resumeScan,
            onCancelScan = appViewModel::cancelScan,
            onRefreshStatus = appViewModel::refreshScanStatus,
            onNavigate = onNavigate,
        )

        AppDestination.Dashboard -> DashboardScreen(
            state = state,
            onRefresh = appViewModel::refreshDashboard,
            onStartScan = appViewModel::startScan,
            onPauseScan = appViewModel::pauseScan,
            onResumeScan = appViewModel::resumeScan,
            onCancelScan = appViewModel::cancelScan,
            onNavigate = onNavigate,
        )

        AppDestination.LibraryBrowser -> LibraryBrowserScreen(
            state = state,
            onSearchByFilename = appViewModel::searchByFilename,
            onSearchByImageId = appViewModel::searchByImageId,
            onAdvancedSearch = appViewModel::runAdvancedSearch,
            onClearResults = appViewModel::clearSearchResults,
            onPreviewFileOperations = appViewModel::previewFileOperations,
            onExecuteFileOperations = appViewModel::executeFileOperations,
            onExecuteFileOperationSequence = appViewModel::executeFileOperationSequence,
            onUndoFileOperations = appViewModel::undoLastFileOperations,
            onOpenImage = {
                appViewModel.selectImage(it)
                onNavigate(AppDestination.ImageViewer)
            },
            onSetFavorite = appViewModel::setImageFavorite,
            onSetRating = appViewModel::setImageRating,
            onNavigate = onNavigate,
        )

        AppDestination.FolderBrowser -> FolderBrowserScreen(
            state = state,
            onChooseFolder = chooseFolder,
            onAddFolder = addFolderToManager,
            onStartScan = appViewModel::startScan,
            onRescanFolder = appViewModel::rescanFolder,
            onRescanEnabledFolders = appViewModel::rescanEnabledFolders,
            onSetFolderEnabled = appViewModel::setLibraryFolderEnabled,
            onRemoveFolder = appViewModel::removeLibraryFolder,
            onRefreshStatus = appViewModel::refreshScanStatus,
            onNavigate = onNavigate,
        )

        AppDestination.ImageViewer -> ImageViewerScreen(
            state = state,
            imageUrl = appViewModel.selectedImageUrl(),
            onSetFavorite = appViewModel::setImageFavorite,
            onSetRating = appViewModel::setImageRating,
            onSetTags = appViewModel::setImageTags,
            onNavigate = onNavigate,
        )

        AppDestination.RecognitionResults -> DataOverviewScreen(
            title = "Recognition Results",
            lines = listOf(
                "Review queue items: ${state.reviewQueue.size}",
                "Knowledge packs: ${state.knowledgePacks.size}",
                "Downloads tracked: ${state.downloads.size}",
            ),
            onNavigate = onNavigate,
        )

        AppDestination.ReviewQueue -> ReviewQueueScreen(
            items = state.reviewQueue,
            onApprove = appViewModel::approveReview,
            onReject = appViewModel::rejectReview,
            onUndo = appViewModel::undoReview,
            onNavigate = onNavigate,
        )

        AppDestination.Search -> SearchScreen(
            title = "Search",
            state = state,
            mode = "search",
            onSearchByFilename = appViewModel::searchByFilename,
            onSearchByImageId = appViewModel::searchByImageId,
            onAdvancedSearch = appViewModel::runAdvancedSearch,
            onSemanticSearch = appViewModel::runSemanticSearch,
            onClearResults = appViewModel::clearSearchResults,
            onOpenImage = {
                appViewModel.selectImage(it)
                onNavigate(AppDestination.ImageViewer)
            },
            onSetFavorite = appViewModel::setImageFavorite,
            onSetRating = appViewModel::setImageRating,
            onNavigate = onNavigate,
        )

        AppDestination.AdvancedSearch -> SearchScreen(
            title = "Advanced Search",
            state = state,
            mode = "advanced",
            onSearchByFilename = appViewModel::searchByFilename,
            onSearchByImageId = appViewModel::searchByImageId,
            onAdvancedSearch = appViewModel::runAdvancedSearch,
            onSemanticSearch = appViewModel::runSemanticSearch,
            onClearResults = appViewModel::clearSearchResults,
            onOpenImage = {
                appViewModel.selectImage(it)
                onNavigate(AppDestination.ImageViewer)
            },
            onSetFavorite = appViewModel::setImageFavorite,
            onSetRating = appViewModel::setImageRating,
            onNavigate = onNavigate,
        )

        AppDestination.SemanticSearch -> SearchScreen(
            title = "Semantic Search",
            state = state,
            mode = "semantic",
            onSearchByFilename = appViewModel::searchByFilename,
            onSearchByImageId = appViewModel::searchByImageId,
            onAdvancedSearch = appViewModel::runAdvancedSearch,
            onSemanticSearch = appViewModel::runSemanticSearch,
            onClearResults = appViewModel::clearSearchResults,
            onOpenImage = {
                appViewModel.selectImage(it)
                onNavigate(AppDestination.ImageViewer)
            },
            onSetFavorite = appViewModel::setImageFavorite,
            onSetRating = appViewModel::setImageRating,
            onNavigate = onNavigate,
        )

        AppDestination.CharacterPage -> DataOverviewScreen(
            title = "Character Page",
            lines = state.tags.take(25).ifEmpty { listOf("No tags available yet.") },
            onNavigate = onNavigate,
        )

        AppDestination.SeriesPage -> DataOverviewScreen(
            title = "Series Page",
            lines = state.collections.take(25).map { it["name"]?.toString().orEmpty().ifBlank { it.toString() } }
                .ifEmpty { listOf("No collection metadata available yet.") },
            onNavigate = onNavigate,
        )

        AppDestination.Collections -> MapListScreen(
            title = "Collections",
            items = state.collections,
            onNavigate = onNavigate,
        )

        AppDestination.Tags -> TagScreen(
            tags = state.tags,
            onNavigate = onNavigate,
        )

        AppDestination.BulkOperations -> FileManagerScreen(
            state = state,
            onPreview = appViewModel::previewFileOperations,
            onExecute = appViewModel::executeFileOperations,
            onUndo = appViewModel::undoLastFileOperations,
            onClear = appViewModel::clearFileOperationPreview,
            onNavigate = onNavigate,
        )

        AppDestination.KnowledgePacks -> MapListScreen(
            title = "Knowledge Packs",
            items = state.knowledgePacks,
            onNavigate = onNavigate,
        )

        AppDestination.Downloads -> MapListScreen(
            title = "Downloads",
            items = state.downloads,
            onNavigate = onNavigate,
        )

        AppDestination.Automation -> DataOverviewScreen(
            title = "Automation",
            lines = listOf(
                "Scan status: ${state.scanStatus}",
                "Scan progress: ${state.scanProgress.toInt()}%",
                "Discovered images in current scan: ${state.scanDiscoveredImages}",
            ),
            onNavigate = onNavigate,
        )

        AppDestination.PluginManager -> DataOverviewScreen(
            title = "Plugin Manager",
            lines = listOf(
                "Plugins are surfaced by the standalone runtime.",
                "Standalone runtime is active for Android.",
            ),
            onNavigate = onNavigate,
        )

        AppDestination.Statistics -> StatisticsScreen(
            state = state,
            onRefresh = {
                appViewModel.refreshDashboard()
                appViewModel.refreshScanStatistics()
            },
            onNavigate = onNavigate,
        )

        AppDestination.Logs -> DataOverviewScreen(
            title = "Logs",
            lines = listOf(
                "Runtime errors are shown on Dashboard.",
                "Current error: ${state.errorMessage ?: "none"}",
            ),
            onNavigate = onNavigate,
        )

        AppDestination.Settings -> SettingsScreen(
            state = state,
            onChooseFolder = chooseFolder,
            onAddFolder = addFolderToManager,
            onSetFolderEnabled = appViewModel::setLibraryFolderEnabled,
            onRemoveFolder = appViewModel::removeLibraryFolder,
            onRescanFolder = appViewModel::rescanFolder,
            onRescanEnabledFolders = appViewModel::rescanEnabledFolders,
            onRebuildSearchIndex = appViewModel::rebuildSearchIndex,
            onOptimizeDatabase = appViewModel::optimizeDatabase,
            onMaintainThumbnailCache = appViewModel::maintainThumbnailCache,
            onClearThumbnailCache = appViewModel::clearThumbnailCache,
            onUpdateSetting = appViewModel::updateLibrarySetting,
            onLoadSetting = appViewModel::loadLibrarySetting,
            onRefresh = {
                appViewModel.refreshDashboard()
                appViewModel.refreshScanStatus()
            },
            onNavigate = onNavigate,
        )

        AppDestination.About -> DataOverviewScreen(
            title = "About",
            lines = listOf(
                "AI Illustration Library Manager",
                "Android standalone runtime edition",
                "Version 2.0.0",
            ),
            onNavigate = onNavigate,
        )
    }
}

private fun persistAndVerifyTreePermission(context: Context, uri: Uri): Boolean {
    val resolver = context.contentResolver
    val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
    val granted = runCatching {
        resolver.takePersistableUriPermission(uri, flags)
        true
    }.getOrElse { error ->
        Log.e(SAF_PERMISSION_TAG, "takePersistableUriPermission failed for $uri", error)
        false
    }
    if (!granted) {
        return false
    }
    return hasPersistedTreePermission(context, uri.toString())
}

private fun hasPersistedTreePermission(context: Context, uriText: String): Boolean {
    val resolver = context.contentResolver
    val target = Uri.parse(uriText).normalizeScheme().toString()
    val match = resolver.persistedUriPermissions.firstOrNull {
        it.uri.normalizeScheme().toString() == target
    }
    if (match == null) {
        Log.w(SAF_PERMISSION_TAG, "No persisted URI permission found for $uriText")
        return false
    }
    val hasRead = match.isReadPermission
    val hasWrite = match.isWritePermission
    if (!hasRead || !hasWrite) {
        Log.w(
            SAF_PERMISSION_TAG,
            "Persisted URI permission incomplete for $uriText (read=$hasRead, write=$hasWrite)",
        )
        return false
    }
    return true
}

@Composable
private fun SplashScreen(
    state: AppUiState,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("AI Illustration Library Manager", style = MaterialTheme.typography.headlineMedium)
        Text("Backend status: ${state.health["status"] ?: state.health["healthy"] ?: "unknown"}")

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = { onNavigate(AppDestination.FirstLaunchWizard) }) {
                Text("First Launch Setup")
            }
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) {
                Text("Open Dashboard")
            }
        }
    }
}

@Composable
private fun FirstLaunchScreen(
    state: AppUiState,
    onChooseFolder: () -> Unit,
    onStartScan: () -> Unit,
    onPauseScan: () -> Unit,
    onResumeScan: () -> Unit,
    onCancelScan: () -> Unit,
    onRefreshStatus: () -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("First Launch Wizard", style = MaterialTheme.typography.headlineMedium)

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = onRefreshStatus) {
                Text("Refresh Status")
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Current library folder URI:")
                Text(
                    text = state.selectedLibraryUri.ifBlank { "No folder selected yet." },
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
                Button(onClick = onChooseFolder) {
                    Text(if (state.selectedLibraryUri.isBlank()) "Choose Folder (SAF)" else "Change Folder")
                }
            }
        }

        ScanControlsCard(
            state = state,
            onStartScan = onStartScan,
            onPauseScan = onPauseScan,
            onResumeScan = onResumeScan,
            onCancelScan = onCancelScan,
        )

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = { onNavigate(AppDestination.Dashboard) }, enabled = state.firstLaunchCompleted) {
                Text("Finish Setup")
            }
            Button(onClick = { onNavigate(AppDestination.FolderBrowser) }) {
                Text("Open Folder Browser")
            }
        }
    }
}

@Composable
private fun DashboardScreen(
    state: AppUiState,
    onRefresh: () -> Unit,
    onStartScan: () -> Unit,
    onPauseScan: () -> Unit,
    onResumeScan: () -> Unit,
    onCancelScan: () -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Dashboard", style = MaterialTheme.typography.headlineMedium)

        if (state.errorMessage != null) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "Last error: ${state.errorMessage}",
                    modifier = Modifier.padding(12.dp),
                )
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Health: ${state.health["status"] ?: state.health["healthy"] ?: "unknown"}", style = MaterialTheme.typography.bodyMedium)
                Text("Runtime: Android standalone", style = MaterialTheme.typography.bodyMedium)
                Text("Library URI configured: ${if (state.selectedLibraryUri.isBlank()) "no" else "yes"}", style = MaterialTheme.typography.bodyMedium)
                Text("Total images: ${state.stats["total_images"] ?: state.images.size}", style = MaterialTheme.typography.bodyMedium)
                Text("Folders: ${state.stats["total_folders"] ?: state.libraryFolders.size}", style = MaterialTheme.typography.bodyMedium)
                Text("Tags: ${state.tags.size}", style = MaterialTheme.typography.bodyMedium)
            }
        }

        if (state.images.isNotEmpty()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Library Preview", style = MaterialTheme.typography.titleMedium)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        state.images.take(4).forEach { image ->
                            val title = image["filename"]?.toString().orEmpty().ifBlank { "Untitled image" }
                            val favorite = image.favoriteFlag()
                            val rating = image.ratingValue()
                            val thumb = image["thumbnail_url"]?.toString()?.takeIf { it.isNotBlank() }
                                ?: image["file_url"]?.toString()?.takeIf { it.isNotBlank() }

                            Card(modifier = Modifier.width(260.dp)) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(8.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                                ) {
                                    if (!thumb.isNullOrBlank()) {
                                        ImageTile(
                                            model = thumb,
                                            contentDescription = title,
                                            modifier = Modifier
                                                .width(124.dp)
                                                .height(96.dp),
                                        )
                                    } else {
                                        Spacer(modifier = Modifier.width(124.dp).height(96.dp))
                                    }
                                    Column(verticalArrangement = Arrangement.spacedBy(4.dp), modifier = Modifier.weight(1f)) {
                                        Text(title, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                        Text(
                                            buildString {
                                                if (favorite) append("Fav")
                                                if (rating > 0) {
                                                    if (isNotEmpty()) append(" • ")
                                                    append("★$rating")
                                                }
                                                if (isEmpty()) append("—")
                                            },
                                            style = MaterialTheme.typography.bodySmall,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        ScanControlsCard(
            state = state,
            onStartScan = onStartScan,
            onPauseScan = onPauseScan,
            onResumeScan = onResumeScan,
            onCancelScan = onCancelScan,
        )

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Library Browser", style = MaterialTheme.typography.titleMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    Button(onClick = onRefresh) {
                        Text("Refresh")
                    }
                    Button(onClick = { onNavigate(AppDestination.LibraryBrowser) }) {
                        Text("Open Library")
                    }
                    Button(onClick = { onNavigate(AppDestination.Settings) }) {
                        Text("Settings")
                    }
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            AppDestination.entries
                .filter { it != AppDestination.Splash }
                .take(8)
                .forEach { destination ->
                    AssistChip(onClick = { onNavigate(destination) }, label = { Text(destination.title) })
                }
        }
    }
}

@Composable
private fun FolderBrowserScreen(
    state: AppUiState,
    onChooseFolder: () -> Unit,
    onAddFolder: () -> Unit,
    onStartScan: () -> Unit,
    onRescanFolder: (String) -> Unit,
    onRescanEnabledFolders: () -> Unit,
    onSetFolderEnabled: (String, Boolean) -> Unit,
    onRemoveFolder: (String) -> Unit,
    onRefreshStatus: () -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Folder Browser", style = MaterialTheme.typography.headlineMedium)
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Selected folder URI")
                Text(
                    text = state.selectedLibraryUri.ifBlank { "No SAF folder selected." },
                    maxLines = 4,
                    overflow = TextOverflow.Ellipsis,
                )
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    Button(onClick = onChooseFolder) {
                        Text(if (state.selectedLibraryUri.isBlank()) "Choose Folder" else "Change Folder")
                    }
                    Button(onClick = onAddFolder) {
                        Text("Add Folder")
                    }
                    Button(onClick = onRefreshStatus) {
                        Text("Refresh Status")
                    }
                }

                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    Button(onClick = onStartScan, enabled = state.selectedLibraryUri.isNotBlank()) {
                        Text("Scan Selected")
                    }
                    Button(onClick = onRescanEnabledFolders) {
                        Text("Rescan Enabled")
                    }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Folder Manager", style = MaterialTheme.typography.titleMedium)
                if (state.libraryFolders.isEmpty()) {
                    Text("No folders registered yet.")
                } else {
                    LazyColumn(
                        modifier = Modifier.heightIn(max = 320.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(state.libraryFolders) { folder ->
                            val folderUri = folder["folder_uri"]?.toString().orEmpty()
                            val enabled = folder["enabled"] as? Boolean ?: false
                            val lastStatus = folder["last_scan_status"]?.toString().orEmpty()
                            val lastCount = folder["last_scan_count"]?.toString().orEmpty()
                            Card(modifier = Modifier.fillMaxWidth()) {
                                Column(
                                    modifier = Modifier.padding(10.dp),
                                    verticalArrangement = Arrangement.spacedBy(6.dp),
                                ) {
                                    Text(folderUri.ifBlank { "(empty uri)" }, maxLines = 3, overflow = TextOverflow.Ellipsis)
                                    Text("Enabled: $enabled | Last status: ${lastStatus.ifBlank { "n/a" }} | Last count: ${lastCount.ifBlank { "0" }}")
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Button(onClick = { onSetFolderEnabled(folderUri, !enabled) }, enabled = folderUri.isNotBlank()) {
                                            Text(if (enabled) "Disable" else "Enable")
                                        }
                                        Button(onClick = { onRescanFolder(folderUri) }, enabled = folderUri.isNotBlank()) {
                                            Text("Rescan")
                                        }
                                        Button(onClick = { onRemoveFolder(folderUri) }, enabled = folderUri.isNotBlank()) {
                                            Text("Remove")
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) {
                Text("Dashboard")
            }
            Button(onClick = { onNavigate(AppDestination.LibraryBrowser) }) {
                Text("Library")
            }
        }
    }
}

@Composable
@OptIn(ExperimentalLayoutApi::class)
private fun LibraryBrowserScreen(
    state: AppUiState,
    onSearchByFilename: (String) -> Unit,
    onSearchByImageId: (String) -> Unit,
    onAdvancedSearch: (Map<String, Any>) -> Unit,
    onClearResults: () -> Unit,
    onPreviewFileOperations: (Map<String, Any>) -> Unit,
    onExecuteFileOperations: (Map<String, Any>) -> Unit,
    onExecuteFileOperationSequence: (List<Map<String, Any>>) -> Unit,
    onUndoFileOperations: () -> Unit,
    onOpenImage: (Map<String, Any>) -> Unit,
    onSetFavorite: (Int, Boolean) -> Unit,
    onSetRating: (Int, Int) -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    var searchQuery by rememberSaveable { mutableStateOf("") }
    var imageIdQuery by rememberSaveable { mutableStateOf("") }
    var fullTextQuery by rememberSaveable { mutableStateOf("") }
    var sortBy by rememberSaveable { mutableStateOf("date_added") }
    var sortDirection by rememberSaveable { mutableStateOf("desc") }
    var showSearch by rememberSaveable { mutableStateOf(true) }
    var showSort by rememberSaveable { mutableStateOf(false) }
    var showFilters by rememberSaveable { mutableStateOf(false) }
    var favoritesOnly by rememberSaveable { mutableStateOf(false) }
    var minRatingText by rememberSaveable { mutableStateOf("") }
    var tagsQuery by rememberSaveable { mutableStateOf("") }
    var minWidthText by rememberSaveable { mutableStateOf("") }
    var minHeightText by rememberSaveable { mutableStateOf("") }
    var formatQuery by rememberSaveable { mutableStateOf("") }
    var orientationQuery by rememberSaveable { mutableStateOf("any") }
    var folderQuery by rememberSaveable { mutableStateOf("") }
    var includeHidden by rememberSaveable { mutableStateOf(false) }
    var missingOnly by rememberSaveable { mutableStateOf(false) }
    var selectionMode by rememberSaveable { mutableStateOf(false) }
    var selectedImageIds by rememberSaveable { mutableStateOf(setOf<Int>()) }
    var selectedFolderUri by rememberSaveable { mutableStateOf("") }
    var selectedTargetFolderUri by rememberSaveable { mutableStateOf("") }
    var conflictMode by rememberSaveable { mutableStateOf("rename") }
    var targetMenuExpanded by rememberSaveable { mutableStateOf(false) }
    var conflictMenuExpanded by rememberSaveable { mutableStateOf(false) }

    var showCreateFolderDialog by rememberSaveable { mutableStateOf(false) }
    var showRenameImageDialog by rememberSaveable { mutableStateOf(false) }
    var showBatchRenameDialog by rememberSaveable { mutableStateOf(false) }
    var showRenameFolderDialog by rememberSaveable { mutableStateOf(false) }
    var showMoveDialog by rememberSaveable { mutableStateOf(false) }
    var showCopyDialog by rememberSaveable { mutableStateOf(false) }
    var showDeleteDialog by rememberSaveable { mutableStateOf(false) }

    var renameImageName by rememberSaveable { mutableStateOf("") }
    var renamePattern by rememberSaveable { mutableStateOf("renamed_{n}") }
    var renameFolderName by rememberSaveable { mutableStateOf("") }
    var createFolderName by rememberSaveable { mutableStateOf("") }
    var moveDeleteSourceFolderAfterMove by rememberSaveable { mutableStateOf(true) }

    LaunchedEffect(
        searchQuery,
        imageIdQuery,
        fullTextQuery,
        sortBy,
        sortDirection,
        favoritesOnly,
        minRatingText,
        tagsQuery,
        minWidthText,
        minHeightText,
        formatQuery,
        orientationQuery,
        folderQuery,
        includeHidden,
        missingOnly,
    ) {
        delay(250)
        val imageId = imageIdQuery.trim()
        if (imageId.isNotBlank()) {
            onSearchByImageId(imageId)
            return@LaunchedEffect
        }

        val payload = mutableMapOf<String, Any>(
            "query" to searchQuery,
            "full_text" to fullTextQuery,
            "sort_by" to sortBy,
            "sort_direction" to sortDirection,
            "favorites_only" to favoritesOnly,
            "include_hidden" to includeHidden,
            "missing_only" to missingOnly,
            "include_inactive" to missingOnly,
            "page" to 1,
            "page_size" to 0,
        )
        minRatingText.toIntOrNull()?.let { payload["min_rating"] = it }
        minWidthText.toIntOrNull()?.let { payload["min_width"] = it }
        minHeightText.toIntOrNull()?.let { payload["min_height"] = it }
        if (formatQuery.isNotBlank()) payload["file_format"] = formatQuery
        if (orientationQuery != "any") payload["orientation"] = orientationQuery
        if (folderQuery.isNotBlank()) payload["folder_query"] = folderQuery
        val tags = tagsQuery.split(',', '|').map { it.trim() }.filter { it.isNotBlank() }
        if (tags.isNotEmpty()) payload["tags"] = tags
        onAdvancedSearch(payload)
    }

    val configuration = LocalConfiguration.current
    val screenWidthDp = configuration.screenWidthDp
    val adaptiveMinSize = if (screenWidthDp >= 900) 220.dp else 180.dp
    val images = if (state.searchResults.isNotEmpty()) state.searchResults else state.images
    val totalCount = if (state.totalResults > 0 || images.isEmpty()) state.totalResults else images.size
    val allFolders = state.libraryFolders.mapNotNull { it["folder_uri"]?.toString() }.distinct()
    val selectedFolderImages = if (selectedFolderUri.isBlank()) emptyList() else state.images.filter { it.folderUriValue() == selectedFolderUri }
    val selectedFolderImageIds = selectedFolderImages.mapNotNull { it.imageId() }.toSet()

    val selectedOperationKind = when {
        selectedImageIds.isNotEmpty() -> "images"
        selectedFolderUri.isNotBlank() -> "folder"
        else -> "none"
    }

    val canCreateFolder = allFolders.isNotEmpty()
    val canRename = selectedImageIds.size == 1 || selectedFolderUri.isNotBlank() || selectedImageIds.size > 1
    val canMove = selectedImageIds.isNotEmpty() || selectedFolderImageIds.isNotEmpty()
    val canCopy = selectedImageIds.isNotEmpty() || selectedFolderImageIds.isNotEmpty()
    val canDelete = selectedImageIds.isNotEmpty() || selectedFolderUri.isNotBlank()

    val activeFilterChips = buildList {
        if (favoritesOnly) add("favorites")
        if (minRatingText.isNotBlank()) add("rating>=${minRatingText}")
        if (tagsQuery.isNotBlank()) add("tags")
        if (minWidthText.isNotBlank() || minHeightText.isNotBlank()) add("resolution")
        if (formatQuery.isNotBlank()) add("format")
        if (orientationQuery != "any") add("orientation")
        if (folderQuery.isNotBlank()) add("folder")
        if (includeHidden) add("hidden")
        if (missingOnly) add("missing")
        if (fullTextQuery.isNotBlank()) add("full-text")
    }

    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = adaptiveMinSize),
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 12.dp, vertical = 8.dp),
        contentPadding = PaddingValues(bottom = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 12.dp)) {
                Text("Library Browser", style = MaterialTheme.typography.headlineMedium)
                Text("Results: $totalCount")
            }
        }

        item(span = { GridItemSpan(maxLineSpan) }) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("File Manager", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Selection: ${if (selectedOperationKind == "images") "${selectedImageIds.size} image(s)" else if (selectedOperationKind == "folder") "folder selected" else "none"}",
                        style = MaterialTheme.typography.bodySmall,
                    )

                    if (allFolders.isNotEmpty()) {
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            allFolders.forEach { folderUri ->
                                AssistChip(
                                    onClick = {
                                        selectedFolderUri = if (selectedFolderUri == folderUri) "" else folderUri
                                    },
                                    label = { Text(if (selectedFolderUri == folderUri) "[${folderLabelFromUri(folderUri)}]" else folderLabelFromUri(folderUri)) },
                                )
                            }
                        }
                    }

                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { showCreateFolderDialog = true }, enabled = canCreateFolder) { Text("Create Folder") }
                        Button(
                            onClick = {
                                when {
                                    selectedImageIds.size > 1 -> showBatchRenameDialog = true
                                    selectedImageIds.size == 1 -> {
                                        renameImageName = ""
                                        showRenameImageDialog = true
                                    }
                                    selectedFolderUri.isNotBlank() -> {
                                        renameFolderName = ""
                                        showRenameFolderDialog = true
                                    }
                                }
                            },
                            enabled = canRename,
                        ) { Text("Rename") }
                        Button(onClick = { showMoveDialog = true }, enabled = canMove) { Text("Move") }
                        Button(onClick = { showCopyDialog = true }, enabled = canCopy) { Text("Copy") }
                        Button(onClick = { showDeleteDialog = true }, enabled = canDelete) { Text("Delete") }
                        Button(
                            onClick = {
                                selectionMode = !selectionMode
                                if (!selectionMode) {
                                    selectedImageIds = emptySet()
                                }
                            },
                        ) { Text(if (selectionMode) "Batch Select: ON" else "Batch Select") }
                        Button(onClick = onUndoFileOperations, enabled = state.fileOperationUndoAvailable && !state.fileOperationRunning) { Text("Undo Last") }
                    }

                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("Conflict")
                        Box {
                            Button(onClick = { conflictMenuExpanded = true }) {
                                Text(
                                    when (conflictMode) {
                                        "overwrite" -> "Overwrite"
                                        "skip" -> "Skip"
                                        else -> "Keep both"
                                    },
                                )
                            }
                            DropdownMenu(expanded = conflictMenuExpanded, onDismissRequest = { conflictMenuExpanded = false }) {
                                listOf(
                                    "rename" to "Keep both",
                                    "overwrite" to "Overwrite",
                                    "skip" to "Skip",
                                ).forEach { (mode, label) ->
                                    DropdownMenuItem(
                                        text = { Text(label) },
                                        onClick = {
                                            conflictMode = mode
                                            conflictMenuExpanded = false
                                        },
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        item(span = { GridItemSpan(maxLineSpan) }) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { showSearch = !showSearch }) { Text(if (showSearch) "▼ Search" else "► Search") }
                Button(onClick = { showSort = !showSort }) { Text(if (showSort) "▼ Sort" else "► Sort") }
                Button(onClick = { showFilters = !showFilters }) { Text(if (showFilters) "▼ Filters" else "► Filters") }
                Button(onClick = {
                    searchQuery = ""
                    imageIdQuery = ""
                    fullTextQuery = ""
                    tagsQuery = ""
                    minRatingText = ""
                    minWidthText = ""
                    minHeightText = ""
                    formatQuery = ""
                    folderQuery = ""
                    favoritesOnly = false
                    includeHidden = false
                    missingOnly = false
                    orientationQuery = "any"
                    sortBy = "date_added"
                    sortDirection = "desc"
                    onClearResults()
                }) { Text("Clear") }
            }
        }

        if (showSearch) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Card(modifier = Modifier.fillMaxWidth().animateContentSize()) {
                    Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(value = searchQuery, onValueChange = { searchQuery = it }, modifier = Modifier.fillMaxWidth(), singleLine = true, label = { Text("Filename search") })
                        OutlinedTextField(value = imageIdQuery, onValueChange = { imageIdQuery = it }, modifier = Modifier.fillMaxWidth(), singleLine = true, label = { Text("Image ID search") })
                        OutlinedTextField(value = fullTextQuery, onValueChange = { fullTextQuery = it }, modifier = Modifier.fillMaxWidth(), singleLine = true, label = { Text("Full-text search") })
                    }
                }
            }
        }

        if (showSort) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Card(modifier = Modifier.fillMaxWidth().animateContentSize()) {
                    Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Sort", style = MaterialTheme.typography.titleSmall)
                        val options = listOf(
                            "filename_asc" to "Filename A→Z",
                            "filename_desc" to "Filename Z→A",
                            "date_added" to "Date Added",
                            "date_modified" to "Date Modified",
                            "resolution" to "Resolution",
                            "size" to "File Size",
                            "rating" to "Rating",
                            "favorites" to "Favorites First",
                            "random" to "Random",
                        )
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            options.forEach { (value, label) ->
                                AssistChip(onClick = {
                                    when (value) {
                                        "filename_asc" -> { sortBy = "filename"; sortDirection = "asc" }
                                        "filename_desc" -> { sortBy = "filename"; sortDirection = "desc" }
                                        else -> { sortBy = value; sortDirection = "desc" }
                                    }
                                }, label = {
                                    val selected =
                                        (value == "filename_asc" && sortBy == "filename" && sortDirection == "asc") ||
                                            (value == "filename_desc" && sortBy == "filename" && sortDirection == "desc") ||
                                            (value !in setOf("filename_asc", "filename_desc") && sortBy == value)
                                    Text(if (selected) "[$label]" else label)
                                })
                            }
                        }
                    }
                }
            }
        }

        if (showFilters) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Card(modifier = Modifier.fillMaxWidth().animateContentSize()) {
                    Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Filters", style = MaterialTheme.typography.titleSmall)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            AssistChip(onClick = { favoritesOnly = !favoritesOnly }, label = { Text(if (favoritesOnly) "Favorites:on" else "Favorites") })
                            AssistChip(onClick = { includeHidden = !includeHidden }, label = { Text(if (includeHidden) "Hidden:on" else "Hidden") })
                            AssistChip(onClick = { missingOnly = !missingOnly }, label = { Text(if (missingOnly) "Missing:on" else "Missing") })
                        }
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedTextField(value = minRatingText, onValueChange = { minRatingText = it }, singleLine = true, label = { Text("Min rating") })
                            OutlinedTextField(value = tagsQuery, onValueChange = { tagsQuery = it }, singleLine = true, label = { Text("Tags") })
                            OutlinedTextField(value = minWidthText, onValueChange = { minWidthText = it }, singleLine = true, label = { Text("Min width") })
                            OutlinedTextField(value = minHeightText, onValueChange = { minHeightText = it }, singleLine = true, label = { Text("Min height") })
                            OutlinedTextField(value = formatQuery, onValueChange = { formatQuery = it }, singleLine = true, label = { Text("Format") })
                            OutlinedTextField(value = folderQuery, onValueChange = { folderQuery = it }, singleLine = true, label = { Text("Folder") })
                        }
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            listOf("any", "portrait", "landscape", "square").forEach { ori ->
                                AssistChip(onClick = { orientationQuery = ori }, label = { Text(if (orientationQuery == ori) "[$ori]" else ori) })
                            }
                        }
                    }
                }
            }
        }

        if (activeFilterChips.isNotEmpty()) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    activeFilterChips.forEach { chip -> AssistChip(onClick = {}, label = { Text(chip) }) }
                }
            }
        }

        if (state.loading) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    CircularProgressIndicator()
                    Text("Loading library...")
                }
            }
        }

        if (images.isEmpty()) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Text("No images match the current search and filters.", modifier = Modifier.padding(12.dp))
                }
            }
        } else {
            items(items = images, key = { item -> "${item["image_id"] ?: 0}:${item["path"] ?: item.hashCode()}" }) { item ->
                val title = item["filename"]?.toString().orEmpty().ifBlank { "Untitled image" }
                val favorite = item.favoriteFlag()
                val rating = item.ratingValue()
                val imageId = item.imageId()
                val isSelected = imageId != null && selectedImageIds.contains(imageId)
                val thumbnailUrl = item["thumbnail_url"]?.toString()?.takeIf { it.isNotBlank() } ?: item["file_url"]?.toString()?.takeIf { it.isNotBlank() }
                val cardHeight = 280.dp
                val thumbHeight = 210.dp

                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .combinedClickable(
                            onClick = {
                                if (selectionMode && imageId != null) {
                                    selectedImageIds = if (isSelected) selectedImageIds - imageId else selectedImageIds + imageId
                                } else {
                                    onOpenImage(item)
                                }
                            },
                            onLongClick = {
                                if (imageId != null) {
                                    selectionMode = true
                                    selectedImageIds = if (isSelected) selectedImageIds - imageId else selectedImageIds + imageId
                                }
                            },
                        ),
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(cardHeight)
                            .padding(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        if (!thumbnailUrl.isNullOrBlank()) {
                            ImageTile(
                                model = thumbnailUrl,
                                contentDescription = title,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(thumbHeight),
                                contentScale = ContentScale.Crop,
                            )
                        } else {
                            Spacer(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(thumbHeight),
                            )
                        }
                        Text(title, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(
                            buildString {
                                if (isSelected) {
                                    append("Selected")
                                    append(" • ")
                                }
                                if (favorite) append("Fav")
                                if (rating > 0) {
                                    if (isNotEmpty()) append(" • ")
                                    append("★$rating")
                                }
                                if (isEmpty()) append("—")
                            },
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            }
        }

        item(span = { GridItemSpan(maxLineSpan) }) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(vertical = 8.dp)) {
                Button(onClick = { onNavigate(AppDestination.Dashboard) }) { Text("Dashboard") }
                Button(onClick = { onNavigate(AppDestination.Search) }) { Text("Search") }
            }
        }
    }

    if (showCreateFolderDialog) {
        AlertDialog(
            onDismissRequest = { showCreateFolderDialog = false },
            title = { Text("Create Folder") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = createFolderName,
                        onValueChange = { createFolderName = it },
                        singleLine = true,
                        label = { Text("Folder name") },
                    )
                    Box {
                        Button(onClick = { targetMenuExpanded = true }) {
                            Text(if (selectedTargetFolderUri.isBlank()) "Parent folder" else folderLabelFromUri(selectedTargetFolderUri))
                        }
                        DropdownMenu(expanded = targetMenuExpanded, onDismissRequest = { targetMenuExpanded = false }) {
                            allFolders.forEach { folderUri ->
                                DropdownMenuItem(
                                    text = { Text(folderLabelFromUri(folderUri)) },
                                    onClick = {
                                        selectedTargetFolderUri = folderUri
                                        targetMenuExpanded = false
                                    },
                                )
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onExecuteFileOperations(
                            mapOf(
                                "action" to "create_folder",
                                "target_folder_uri" to selectedTargetFolderUri,
                                "folder_name" to createFolderName.trim(),
                                "conflict_mode" to conflictMode,
                            ),
                        )
                        showCreateFolderDialog = false
                    },
                    enabled = createFolderName.isNotBlank() && selectedTargetFolderUri.isNotBlank(),
                ) { Text("Create") }
            },
            dismissButton = { TextButton(onClick = { showCreateFolderDialog = false }) { Text("Cancel") } },
        )
    }

    if (showRenameImageDialog) {
        val imageId = selectedImageIds.firstOrNull()
        AlertDialog(
            onDismissRequest = { showRenameImageDialog = false },
            title = { Text("Rename File") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Image ID: ${imageId ?: 0}")
                    OutlinedTextField(value = renameImageName, onValueChange = { renameImageName = it }, singleLine = true, label = { Text("New name") })
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onExecuteFileOperations(
                            mapOf(
                                "action" to "rename_image",
                                "image_ids" to (imageId?.toString().orEmpty()),
                                "name" to renameImageName.trim(),
                                "conflict_mode" to conflictMode,
                            ),
                        )
                        showRenameImageDialog = false
                    },
                    enabled = imageId != null && renameImageName.isNotBlank(),
                ) { Text("Rename") }
            },
            dismissButton = { TextButton(onClick = { showRenameImageDialog = false }) { Text("Cancel") } },
        )
    }

    if (showBatchRenameDialog) {
        AlertDialog(
            onDismissRequest = { showBatchRenameDialog = false },
            title = { Text("Batch Rename") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Selected images: ${selectedImageIds.size}")
                    OutlinedTextField(value = renamePattern, onValueChange = { renamePattern = it }, singleLine = true, label = { Text("Pattern (use {n})") })
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onExecuteFileOperations(
                            mapOf(
                                "action" to "batch_rename_images",
                                "image_ids" to selectedImageIds.joinToString(","),
                                "pattern" to renamePattern.trim(),
                                "conflict_mode" to conflictMode,
                            ),
                        )
                        showBatchRenameDialog = false
                    },
                    enabled = selectedImageIds.isNotEmpty() && renamePattern.isNotBlank(),
                ) { Text("Rename") }
            },
            dismissButton = { TextButton(onClick = { showBatchRenameDialog = false }) { Text("Cancel") } },
        )
    }

    if (showRenameFolderDialog) {
        AlertDialog(
            onDismissRequest = { showRenameFolderDialog = false },
            title = { Text("Rename Folder") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(folderLabelFromUri(selectedFolderUri))
                    OutlinedTextField(value = renameFolderName, onValueChange = { renameFolderName = it }, singleLine = true, label = { Text("Folder new name") })
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onExecuteFileOperations(
                            mapOf(
                                "action" to "rename_folder",
                                "source_folder_uri" to selectedFolderUri,
                                "folder_name" to renameFolderName.trim(),
                                "conflict_mode" to conflictMode,
                            ),
                        )
                        showRenameFolderDialog = false
                    },
                    enabled = selectedFolderUri.isNotBlank() && renameFolderName.isNotBlank(),
                ) { Text("Rename") }
            },
            dismissButton = { TextButton(onClick = { showRenameFolderDialog = false }) { Text("Cancel") } },
        )
    }

    if (showMoveDialog) {
        val selectedIds = if (selectedImageIds.isNotEmpty()) selectedImageIds else selectedFolderImageIds
        AlertDialog(
            onDismissRequest = { showMoveDialog = false },
            title = { Text(if (selectedImageIds.isNotEmpty()) "Move Images" else "Move Folder") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Items: ${selectedIds.size}")
                    Box {
                        Button(onClick = { targetMenuExpanded = true }) {
                            Text(if (selectedTargetFolderUri.isBlank()) "Target folder" else folderLabelFromUri(selectedTargetFolderUri))
                        }
                        DropdownMenu(expanded = targetMenuExpanded, onDismissRequest = { targetMenuExpanded = false }) {
                            allFolders.forEach { folderUri ->
                                DropdownMenuItem(
                                    text = { Text(folderLabelFromUri(folderUri)) },
                                    onClick = {
                                        selectedTargetFolderUri = folderUri
                                        targetMenuExpanded = false
                                    },
                                )
                            }
                        }
                    }
                    AssistChip(
                        onClick = { moveDeleteSourceFolderAfterMove = !moveDeleteSourceFolderAfterMove },
                        label = {
                            Text(
                                if (moveDeleteSourceFolderAfterMove) {
                                    "Delete source folder after move: on"
                                } else {
                                    "Delete source folder after move: off"
                                },
                            )
                        },
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val movePayload = mapOf(
                            "action" to if (selectedImageIds.size > 1) "batch_move" else "move_images",
                            "image_ids" to selectedIds.joinToString(","),
                            "target_folder_uri" to selectedTargetFolderUri,
                            "conflict_mode" to conflictMode,
                        )
                        if (selectedImageIds.isEmpty() && selectedFolderUri.isNotBlank() && moveDeleteSourceFolderAfterMove) {
                            onExecuteFileOperationSequence(
                                listOf(
                                    movePayload,
                                    mapOf(
                                        "action" to "delete_folder",
                                        "source_folder_uri" to selectedFolderUri,
                                        "conflict_mode" to conflictMode,
                                    ),
                                ),
                            )
                        } else {
                            onExecuteFileOperations(movePayload)
                        }
                        showMoveDialog = false
                    },
                    enabled = selectedIds.isNotEmpty() && selectedTargetFolderUri.isNotBlank(),
                ) { Text("Move") }
            },
            dismissButton = { TextButton(onClick = { showMoveDialog = false }) { Text("Cancel") } },
        )
    }

    if (showCopyDialog) {
        val selectedIds = if (selectedImageIds.isNotEmpty()) selectedImageIds else selectedFolderImageIds
        AlertDialog(
            onDismissRequest = { showCopyDialog = false },
            title = { Text(if (selectedImageIds.isNotEmpty()) "Copy Images" else "Copy Folder") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Items: ${selectedIds.size}")
                    Box {
                        Button(onClick = { targetMenuExpanded = true }) {
                            Text(if (selectedTargetFolderUri.isBlank()) "Target folder" else folderLabelFromUri(selectedTargetFolderUri))
                        }
                        DropdownMenu(expanded = targetMenuExpanded, onDismissRequest = { targetMenuExpanded = false }) {
                            allFolders.forEach { folderUri ->
                                DropdownMenuItem(
                                    text = { Text(folderLabelFromUri(folderUri)) },
                                    onClick = {
                                        selectedTargetFolderUri = folderUri
                                        targetMenuExpanded = false
                                    },
                                )
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onExecuteFileOperations(
                            mapOf(
                                "action" to if (selectedImageIds.size > 1) "batch_copy" else "copy_images",
                                "image_ids" to selectedIds.joinToString(","),
                                "target_folder_uri" to selectedTargetFolderUri,
                                "conflict_mode" to conflictMode,
                            ),
                        )
                        showCopyDialog = false
                    },
                    enabled = selectedIds.isNotEmpty() && selectedTargetFolderUri.isNotBlank(),
                ) { Text("Copy") }
            },
            dismissButton = { TextButton(onClick = { showCopyDialog = false }) { Text("Cancel") } },
        )
    }

    if (showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteDialog = false },
            title = { Text("Delete") },
            text = {
                Text(
                    if (selectedImageIds.isNotEmpty()) {
                        "Delete ${selectedImageIds.size} selected image(s)?"
                    } else {
                        "Delete selected folder?"
                    },
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        if (selectedImageIds.isNotEmpty()) {
                            onExecuteFileOperations(
                                mapOf(
                                    "action" to if (selectedImageIds.size > 1) "batch_delete" else "delete_images",
                                    "image_ids" to selectedImageIds.joinToString(","),
                                    "conflict_mode" to conflictMode,
                                ),
                            )
                        } else if (selectedFolderUri.isNotBlank()) {
                            onExecuteFileOperations(
                                mapOf(
                                    "action" to "delete_folder",
                                    "source_folder_uri" to selectedFolderUri,
                                    "conflict_mode" to conflictMode,
                                ),
                            )
                        }
                        showDeleteDialog = false
                    },
                    enabled = selectedImageIds.isNotEmpty() || selectedFolderUri.isNotBlank(),
                ) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { showDeleteDialog = false }) { Text("Cancel") } },
        )
    }

    if (state.fileOperationRunning) {
        AlertDialog(
            onDismissRequest = {},
            confirmButton = {},
            title = { Text("Progress") },
            text = {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator()
                    Text("Executing file operation...")
                }
            },
        )
    }
}

@Composable
private fun ImageViewerScreen(
    state: AppUiState,
    imageUrl: String?,
    onSetFavorite: (Int, Boolean) -> Unit,
    onSetRating: (Int, Int) -> Unit,
    onSetTags: (Int, String) -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    var tagsText by rememberSaveable { mutableStateOf("") }
    var showMetadata by rememberSaveable { mutableStateOf(true) }

    val selected = state.selectedImage
    val selectedId = selected?.imageId()
    LaunchedEffect(selectedId, selected?.get("metadata")) {
        val metadata = selected?.get("metadata") as? Map<*, *>
        val tags = when (val nested = metadata?.get("tags")) {
            is List<*> -> nested.mapNotNull { it?.toString()?.trim() }.filter { it.isNotBlank() }
            is String -> nested.split('|').map { it.trim() }.filter { it.isNotBlank() }
            else -> emptyList()
        }
        tagsText = tags.joinToString(", ")
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Image Viewer", style = MaterialTheme.typography.headlineMedium)

        if (selected == null) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Text("No image selected. Open an item from Library Browser.", modifier = Modifier.padding(12.dp))
            }
        } else {
            val title = selected["filename"]?.toString().orEmpty().ifBlank { "Untitled image" }
            val imageId = selected.imageId()
            val favorite = selected.favoriteFlag()
            val rating = selected.ratingValue()
            val metadata = selected["metadata"] as? Map<*, *> ?: emptyMap<String, Any>()
            val tags = when (val nested = metadata["tags"]) {
                is List<*> -> nested.mapNotNull { it?.toString()?.trim() }.filter { it.isNotBlank() }
                is String -> nested.split('|').map { it.trim() }.filter { it.isNotBlank() }
                else -> emptyList()
            }
            LaunchedEffect(selectedId, favorite, rating, tags.joinToString("|")) {
                Log.d(
                    UI_TRACE_TAG,
                    "Compose recomposition: imageId=$imageId displayedFavorite=$favorite displayedRating=$rating displayedTags=${tags.joinToString("|")}",
                )
            }

            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (!imageUrl.isNullOrBlank()) {
                        ImageTile(
                            model = imageUrl,
                            contentDescription = title,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(320.dp),
                            contentScale = ContentScale.Fit,
                        )
                    }
                    Text(title, style = MaterialTheme.typography.titleMedium)

                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                            if (imageId != null) {
                                Log.d(UI_TRACE_TAG, "UI click favorite: imageId=$imageId currentFavorite=$favorite nextFavorite=${!favorite}")
                                onSetFavorite(imageId, !favorite)
                            }
                        }, enabled = imageId != null) {
                            Text(if (favorite) "Unfavorite" else "Favorite")
                        }
                        Button(onClick = { showMetadata = !showMetadata }) {
                            Text(if (showMetadata) "Hide Metadata" else "Show Metadata")
                        }
                    }

                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf(0, 1, 2, 3, 4, 5).forEach { candidate ->
                            AssistChip(
                                onClick = {
                                    if (imageId != null) {
                                        Log.d(UI_TRACE_TAG, "UI click rating: imageId=$imageId currentRating=$rating nextRating=$candidate")
                                        onSetRating(imageId, candidate)
                                    }
                                },
                                label = {
                                    val stars = if (candidate == 0) "0" else "★".repeat(candidate)
                                    Text(if (candidate == rating) "[$stars]" else stars)
                                },
                            )
                        }
                    }

                    OutlinedTextField(
                        value = tagsText,
                        onValueChange = { tagsText = it },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text("Tags (comma or | separated)") },
                    )
                    Button(onClick = {
                        if (imageId != null) {
                            Log.d(UI_TRACE_TAG, "UI click tags: imageId=$imageId currentTags=${tags.joinToString("|")} nextTagsCsv=$tagsText")
                            onSetTags(imageId, tagsText)
                        }
                    }, enabled = imageId != null) {
                        Text("Save Tags")
                    }

                    if (showMetadata) {
                        Text("Metadata", style = MaterialTheme.typography.titleSmall)
                        metadataRows(selected).forEach { line ->
                            Text(line, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        }

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onNavigate(AppDestination.LibraryBrowser) }) {
                Text("Back to Library")
            }
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) {
                Text("Dashboard")
            }
        }
    }
}

@Composable
private fun ReviewQueueScreen(
    items: List<Map<String, Any>>,
    onApprove: (String) -> Unit,
    onReject: (String) -> Unit,
    onUndo: (String) -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Review Queue", style = MaterialTheme.typography.headlineMedium)
        Text("Approve | Reject | Undo")

        if (items.isEmpty()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Text("No review items available in local runtime.", modifier = Modifier.padding(12.dp))
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(items) { item ->
                    val id = item["id"]?.toString()
                        ?: item["item_id"]?.toString()
                        ?: item["path"]?.toString()
                        ?: item.hashCode().toString()
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            item.entries.take(8).forEach { entry ->
                                Text("${entry.key}: ${entry.value}")
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(onClick = { onApprove(id) }) {
                                    Text("Approve")
                                }
                                Button(onClick = { onReject(id) }) {
                                    Text("Reject")
                                }
                                Button(onClick = { onUndo(id) }) {
                                    Text("Undo")
                                }
                            }
                        }
                    }
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) {
                Text("Dashboard")
            }
            Button(onClick = { onNavigate(AppDestination.LibraryBrowser) }) {
                Text("Library")
            }
        }
    }
}

@Composable
private fun SearchScreen(
    title: String,
    state: AppUiState,
    mode: String,
    onSearchByFilename: (String) -> Unit,
    onSearchByImageId: (String) -> Unit,
    onAdvancedSearch: (Map<String, Any>) -> Unit,
    onSemanticSearch: (String) -> Unit,
    onClearResults: () -> Unit,
    onOpenImage: (Map<String, Any>) -> Unit,
    onSetFavorite: (Int, Boolean) -> Unit,
    onSetRating: (Int, Int) -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var imageIdQuery by rememberSaveable { mutableStateOf("") }
    var fullText by rememberSaveable { mutableStateOf("") }
    var collection by rememberSaveable { mutableStateOf("") }
    var tagsCsv by rememberSaveable { mutableStateOf("") }
    var taxonomyKey by rememberSaveable { mutableStateOf("") }
    var taxonomyValue by rememberSaveable { mutableStateOf("") }
    var minRatingText by rememberSaveable { mutableStateOf("") }
    var maxRatingText by rememberSaveable { mutableStateOf("") }
    var includeInactive by rememberSaveable { mutableStateOf(false) }
    var favoritesOnly by rememberSaveable { mutableStateOf(false) }
    var sortBy by rememberSaveable { mutableStateOf("import_order") }
    var sortDirection by rememberSaveable { mutableStateOf("desc") }
    var sortMenuExpanded by rememberSaveable { mutableStateOf(false) }

    val results = state.searchResults.ifEmpty { state.images }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(title, style = MaterialTheme.typography.headlineMedium)

        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            label = { Text("Search bar") },
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onSearchByFilename(query) }) {
                Text("Search by filename")
            }
            Button(onClick = onClearResults) {
                Text("Reset")
            }
        }

        OutlinedTextField(
            value = imageIdQuery,
            onValueChange = { imageIdQuery = it },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            label = { Text("Search by image ID") },
        )
        Button(onClick = { onSearchByImageId(imageIdQuery) }) {
            Text("Search ID")
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Sort menu", style = MaterialTheme.typography.titleSmall)
                Button(onClick = { sortMenuExpanded = true }) {
                    Text("Sort: $sortBy ($sortDirection)")
                }
                DropdownMenu(expanded = sortMenuExpanded, onDismissRequest = { sortMenuExpanded = false }) {
                    listOf("import_order", "filename", "date", "size", "resolution", "random").forEach { key ->
                        DropdownMenuItem(
                            text = { Text(key) },
                            onClick = {
                                sortBy = key
                                sortMenuExpanded = false
                            },
                        )
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    AssistChip(onClick = { sortDirection = "asc" }, label = { Text(if (sortDirection == "asc") "Direction: ASC" else "ASC") })
                    AssistChip(onClick = { sortDirection = "desc" }, label = { Text(if (sortDirection == "desc") "Direction: DESC" else "DESC") })
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Filter panel", style = MaterialTheme.typography.titleSmall)
                OutlinedTextField(
                    value = fullText,
                    onValueChange = { fullText = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("Full-text") },
                )
                OutlinedTextField(
                    value = collection,
                    onValueChange = { collection = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("Collection (folder URI)") },
                )
                OutlinedTextField(
                    value = tagsCsv,
                    onValueChange = { tagsCsv = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("Tags (comma or | separated)") },
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = taxonomyKey,
                        onValueChange = { taxonomyKey = it },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text("Taxonomy key") },
                    )
                    OutlinedTextField(
                        value = taxonomyValue,
                        onValueChange = { taxonomyValue = it },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text("Taxonomy value") },
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = minRatingText,
                        onValueChange = { minRatingText = it },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text("Min rating") },
                    )
                    OutlinedTextField(
                        value = maxRatingText,
                        onValueChange = { maxRatingText = it },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text("Max rating") },
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    AssistChip(
                        onClick = { favoritesOnly = !favoritesOnly },
                        label = { Text(if (favoritesOnly) "Favorites only: on" else "Favorites only: off") },
                    )
                    AssistChip(
                        onClick = { includeInactive = !includeInactive },
                        label = { Text(if (includeInactive) "Include inactive: on" else "Include inactive: off") },
                    )
                }

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        val payload = mutableMapOf<String, Any>(
                            "query" to query,
                            "sort_by" to sortBy,
                            "sort_direction" to sortDirection,
                            "favorites_only" to favoritesOnly,
                            "include_inactive" to includeInactive,
                            "page" to 1,
                            "page_size" to 0,
                        )
                        if (fullText.isNotBlank()) payload["full_text"] = fullText
                        if (collection.isNotBlank()) payload["collection"] = collection

                        val tags = tagsCsv
                            .split(',', '|')
                            .map { it.trim() }
                            .filter { it.isNotBlank() }
                        if (tags.isNotEmpty()) payload["tags"] = tags

                        val minRating = minRatingText.toIntOrNull()
                        val maxRating = maxRatingText.toIntOrNull()
                        if (minRating != null) payload["min_rating"] = minRating
                        if (maxRating != null) payload["max_rating"] = maxRating

                        if (taxonomyKey.isNotBlank() && taxonomyValue.isNotBlank()) {
                            payload["taxonomy_filters"] = mapOf(taxonomyKey.trim() to taxonomyValue.trim())
                        }

                        val imageId = imageIdQuery.trim().toIntOrNull()
                        if (imageId != null) {
                            payload["image_id"] = imageId
                        }

                        onAdvancedSearch(payload)
                    }) {
                        Text("Run advanced search")
                    }
                    if (mode == "semantic") {
                        Button(onClick = { onSemanticSearch(query) }) {
                            Text("Run semantic search")
                        }
                    }
                }
            }
        }

        Text("Results: ${results.size}")
        if (state.lastActionMessage != null) {
            Text(state.lastActionMessage)
        }
        if (state.errorMessage != null) {
            Text("Error: ${state.errorMessage}")
        }

        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(results) { item ->
                val caption = item["filename"]?.toString().orEmpty().ifBlank { item["path"]?.toString().orEmpty() }
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onOpenImage(item) },
                ) {
                    Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(caption.ifBlank { "Untitled" })
                        Text(item["path"]?.toString().orEmpty(), maxLines = 2, overflow = TextOverflow.Ellipsis)
                        val imageId = item.imageId()
                        val favorite = item.favoriteFlag()
                        val rating = item.ratingValue()
                        Text("ID: ${imageId ?: "n/a"} | Favorite: $favorite | Rating: $rating")
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = {
                                if (imageId != null) {
                                    onSetFavorite(imageId, !favorite)
                                }
                            }, enabled = imageId != null) {
                                Text(if (favorite) "Unfavorite" else "Favorite")
                            }
                            Button(onClick = {
                                if (imageId != null) {
                                    val next = if (rating >= 5) 0 else rating + 1
                                    onSetRating(imageId, next)
                                }
                            }, enabled = imageId != null) {
                                Text("Rate +1")
                            }
                        }
                    }
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) {
                Text("Dashboard")
            }
            Button(onClick = { onNavigate(AppDestination.LibraryBrowser) }) {
                Text("Library")
            }
        }
    }
}

@Composable
private fun SettingsScreen(
    state: AppUiState,
    onChooseFolder: () -> Unit,
    onAddFolder: () -> Unit,
    onSetFolderEnabled: (String, Boolean) -> Unit,
    onRemoveFolder: (String) -> Unit,
    onRescanFolder: (String) -> Unit,
    onRescanEnabledFolders: () -> Unit,
    onRebuildSearchIndex: () -> Unit,
    onOptimizeDatabase: () -> Unit,
    onMaintainThumbnailCache: (Int) -> Unit,
    onClearThumbnailCache: () -> Unit,
    onUpdateSetting: (String, String) -> Unit,
    onLoadSetting: (String, String) -> Unit,
    onRefresh: () -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    var cacheMbText by rememberSaveable { mutableStateOf("256") }
    var settingKey by rememberSaveable { mutableStateOf("") }
    var settingValue by rememberSaveable { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineMedium)

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onRefresh) {
                Text("Refresh Data")
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Runtime mode: Android standalone")
                Text("Library URI:")
                Text(
                    text = state.selectedLibraryUri.ifBlank { "No folder selected." },
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onChooseFolder) {
                        Text("Choose / Change Library Folder")
                    }
                    Button(onClick = onAddFolder) {
                        Text("Add Folder")
                    }
                    Button(onClick = onRescanEnabledFolders) {
                        Text("Rescan Enabled")
                    }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Folder Manager", style = MaterialTheme.typography.titleMedium)
                if (state.libraryFolders.isEmpty()) {
                    Text("No folders in manager.")
                } else {
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(state.libraryFolders) { folder ->
                            val folderUri = folder["folder_uri"]?.toString().orEmpty()
                            val enabled = folder["enabled"] as? Boolean ?: false
                            Card(modifier = Modifier.fillMaxWidth()) {
                                Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Text(folderUri, maxLines = 3, overflow = TextOverflow.Ellipsis)
                                    Text("Enabled: $enabled")
                                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Button(onClick = { onSetFolderEnabled(folderUri, !enabled) }) {
                                            Text(if (enabled) "Disable" else "Enable")
                                        }
                                        Button(onClick = { onRescanFolder(folderUri) }) {
                                            Text("Rescan")
                                        }
                                        Button(onClick = { onRemoveFolder(folderUri) }) {
                                            Text("Remove")
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Library Maintenance", style = MaterialTheme.typography.titleMedium)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onRebuildSearchIndex) {
                        Text("Rebuild Search Index")
                    }
                    Button(onClick = onOptimizeDatabase) {
                        Text("Optimize Database")
                    }
                }
                OutlinedTextField(
                    value = cacheMbText,
                    onValueChange = { cacheMbText = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("Thumbnail cache max MB") },
                )
                Button(onClick = { onMaintainThumbnailCache(cacheMbText.toIntOrNull() ?: 256) }) {
                    Text("Maintain Thumbnail Cache")
                }
                Button(onClick = onClearThumbnailCache) {
                    Text("Clear Thumbnail Cache")
                }
                if (state.lastMaintenanceResult.isNotEmpty()) {
                    state.lastMaintenanceResult.entries.forEach { entry ->
                        Text("${entry.key}: ${entry.value}")
                    }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Runtime Settings", style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    value = settingKey,
                    onValueChange = { settingKey = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("Setting key") },
                )
                OutlinedTextField(
                    value = settingValue,
                    onValueChange = { settingValue = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("Setting value") },
                )
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { onUpdateSetting(settingKey, settingValue) }) {
                        Text("Save Setting")
                    }
                    Button(onClick = { onLoadSetting(settingKey, "") }) {
                        Text("Load Setting")
                    }
                }
                val loaded = state.settingsValues[settingKey.trim()]
                if (!loaded.isNullOrBlank()) {
                    Text("Loaded value: $loaded")
                }
            }
        }

        if (state.lastActionMessage != null) {
            Text(state.lastActionMessage)
        }
        if (state.errorMessage != null) {
            Text("Error: ${state.errorMessage}")
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) {
                Text("Dashboard")
            }
            Button(onClick = { onNavigate(AppDestination.FirstLaunchWizard) }) {
                Text("Setup Wizard")
            }
        }
    }
}

@Composable
private fun StatisticsScreen(
    state: AppUiState,
    onRefresh: () -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    val imageStats = remember(state.images) { computeImageStats(state.images) }
    val scanStats = remember(state.scanRuns) { computeScanStats(state.scanRuns) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Statistics", style = MaterialTheme.typography.headlineMedium)

        Button(onClick = onRefresh) {
            Text("Refresh Statistics")
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Health: ${state.health["status"] ?: state.health["healthy"] ?: "unknown"}")
                Text("Total images: ${state.stats["total_images"] ?: state.images.size}")
                Text("Total folders: ${state.stats["total_folders"] ?: state.libraryFolders.size}")
                Text("Favorites: ${state.stats["total_favorites"] ?: 0}")
                Text("Average rating: ${state.stats["avg_rating"] ?: 0.0}")
                Text("Tagged images: ${imageStats.taggedImages}")
                Text("Average resolution: ${imageStats.avgResolution}")
                Text("Storage used: ${imageStats.storageUsedMb} MB")
                Text("Largest image: ${imageStats.largestImage}")
                Text("Smallest image: ${imageStats.smallestImage}")
                Text("Scan duration: ${scanStats.lastDuration}")
                Text("Last scan: ${scanStats.lastScan}")
                Text("Indexed images: ${state.stats["total_images"] ?: state.images.size}")
                Text("Current scan status: ${state.scanStatus}")
                Text("Current scan discovered images: ${state.scanDiscoveredImages}")
            }
        }

        Text("Scan Statistics", style = MaterialTheme.typography.titleMedium)
        if (state.scanRuns.isEmpty()) {
            Text("No scan runs yet.")
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(state.scanRuns) { run ->
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text("scan_id: ${run["scan_id"]}")
                            Text("folder_uri: ${run["folder_uri"]}")
                            Text("status: ${run["status"]}")
                            Text("discovered_count: ${run["discovered_count"]} | skipped_count: ${run["skipped_count"]}")
                            Text("started_at_ms: ${run["started_at_ms"]}")
                            Text("completed_at_ms: ${run["completed_at_ms"]}")
                            val error = run["error_message"]?.toString().orEmpty()
                            if (error.isNotBlank()) {
                                Text("error_message: $error")
                            }
                        }
                    }
                }
            }
        }

        MapListScreen(
            title = "Raw statistics",
            items = listOf(state.stats),
            onNavigate = onNavigate,
        )
    }
}

private data class ImageAggregateStats(
    val taggedImages: Int,
    val avgResolution: String,
    val storageUsedMb: String,
    val largestImage: String,
    val smallestImage: String,
)

private data class ScanAggregateStats(
    val lastDuration: String,
    val lastScan: String,
)

private fun computeImageStats(images: List<Map<String, Any>>): ImageAggregateStats {
    if (images.isEmpty()) {
        return ImageAggregateStats(0, "n/a", "0.00", "n/a", "n/a")
    }

    var tagged = 0
    var totalArea = 0L
    var areaCount = 0
    var totalSize = 0L
    var largest: Pair<String, Long>? = null
    var smallest: Pair<String, Long>? = null

    for (image in images) {
        val metadata = image["metadata"] as? Map<*, *> ?: emptyMap<String, Any>()
        val tags = (metadata["tags"] as? List<*>) ?: emptyList<Any>()
        if (tags.isNotEmpty()) {
            tagged += 1
        }

        val width = metadata["width"].asIntNullable()
        val height = metadata["height"].asIntNullable()
        if (width != null && height != null && width > 0 && height > 0) {
            totalArea += width.toLong() * height.toLong()
            areaCount += 1
        }

        val size = metadata["size_bytes"].asLongNullable() ?: 0L
        totalSize += size
        val name = image["filename"]?.toString().orEmpty().ifBlank { image["path"]?.toString().orEmpty() }
        if (largest == null || size > largest!!.second) {
            largest = name to size
        }
        if (smallest == null || size < smallest!!.second) {
            smallest = name to size
        }
    }

    val avgResolution = if (areaCount == 0) {
        "n/a"
    } else {
        val avgArea = totalArea / max(areaCount, 1)
        "${avgArea} px^2"
    }

    return ImageAggregateStats(
        taggedImages = tagged,
        avgResolution = avgResolution,
        storageUsedMb = "%.2f".format(totalSize.toDouble() / (1024.0 * 1024.0)),
        largestImage = largest?.let { "${it.first} (${humanBytes(it.second)})" } ?: "n/a",
        smallestImage = smallest?.let { "${it.first} (${humanBytes(it.second)})" } ?: "n/a",
    )
}

private fun computeScanStats(scanRuns: List<Map<String, Any>>): ScanAggregateStats {
    val latest = scanRuns.firstOrNull()
    if (latest == null) {
        return ScanAggregateStats("n/a", "n/a")
    }

    val started = latest["started_at_ms"].asLongNullable() ?: 0L
    val completed = latest["completed_at_ms"].asLongNullable() ?: 0L
    val durationMs = if (completed > started && started > 0L) completed - started else 0L
    val durationSec = durationMs.toDouble() / 1000.0

    return ScanAggregateStats(
        lastDuration = if (durationMs > 0L) "${durationSec.roundToInt()} sec" else "n/a",
        lastScan = latest["started_at_ms"]?.toString() ?: "n/a",
    )
}

private fun sortComparator(sortBy: String, sortDirection: String): Comparator<Map<String, Any>> {
    val direction = if (sortDirection.equals("asc", ignoreCase = true)) 1 else -1
    return Comparator { a, b ->
        fun cmpLong(left: Long?, right: Long?): Int {
            return when {
                left == null && right == null -> 0
                left == null -> -1 * direction
                right == null -> 1 * direction
                left < right -> -1 * direction
                left > right -> 1 * direction
                else -> 0
            }
        }

        fun cmpInt(left: Int?, right: Int?): Int {
            return when {
                left == null && right == null -> 0
                left == null -> -1 * direction
                right == null -> 1 * direction
                left < right -> -1 * direction
                left > right -> 1 * direction
                else -> 0
            }
        }

        fun cmpBool(left: Boolean, right: Boolean): Int {
            return when {
                left == right -> 0
                left -> 1 * direction
                else -> -1 * direction
            }
        }

        val result = when (sortBy) {
            "filename" -> a["filename"]?.toString().orEmpty().compareTo(b["filename"]?.toString().orEmpty()) * direction
            "date_added" -> cmpLong(a["date_indexed_ms"].asLongNullable(), b["date_indexed_ms"].asLongNullable())
            "date_modified" -> cmpLong((a["metadata"] as? Map<*, *>)?.get("modified_at_ms").asLongNullable(), (b["metadata"] as? Map<*, *>)?.get("modified_at_ms").asLongNullable())
            "size" -> cmpLong((a["metadata"] as? Map<*, *>)?.get("size_bytes").asLongNullable(), (b["metadata"] as? Map<*, *>)?.get("size_bytes").asLongNullable())
            "resolution" -> {
                val aMeta = a["metadata"] as? Map<*, *>
                val bMeta = b["metadata"] as? Map<*, *>
                val aArea = ((aMeta?.get("width").asIntNullable() ?: 0) * (aMeta?.get("height").asIntNullable() ?: 0)).toLong()
                val bArea = ((bMeta?.get("width").asIntNullable() ?: 0) * (bMeta?.get("height").asIntNullable() ?: 0)).toLong()
                cmpLong(aArea, bArea)
            }
            "rating" -> cmpInt(a.ratingValue(), b.ratingValue())
            "favorites" -> cmpBool(a.favoriteFlag(), b.favoriteFlag())
            "random" -> if (Math.random() < 0.5) -1 else 1
            else -> 0
        }

        if (result != 0) {
            result
        } else {
            a["filename"]?.toString().orEmpty().compareTo(b["filename"]?.toString().orEmpty())
        }
    }
}

private fun Any?.asIntNullable(): Int? = when (this) {
    is Number -> this.toInt()
    is String -> this.toIntOrNull()
    else -> null
}

private fun Any?.asLongNullable(): Long? = when (this) {
    is Number -> this.toLong()
    is String -> this.toLongOrNull()
    else -> null
}

private fun humanBytes(value: Long): String {
    if (value <= 0L) {
        return "0 B"
    }
    val kb = 1024.0
    val mb = kb * 1024.0
    return when {
        value >= mb -> "%.2f MB".format(value / mb)
        value >= kb -> "%.1f KB".format(value / kb)
        else -> "$value B"
    }
}

@Composable
private fun ScanControlsCard(
    state: AppUiState,
    onStartScan: () -> Unit,
    onPauseScan: () -> Unit,
    onResumeScan: () -> Unit,
    onCancelScan: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Scan status: ${state.scanStatus}")
            Text("Discovered images: ${state.scanDiscoveredImages}")
            LinearProgressIndicator(
                progress = (state.scanProgress / 100.0).toFloat().coerceIn(0f, 1f),
                modifier = Modifier.fillMaxWidth(),
            )
            Text("Progress: ${state.scanProgress.toInt()}%")

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onStartScan, enabled = state.selectedLibraryUri.isNotBlank()) {
                    Text("Start")
                }
                Button(onClick = onPauseScan, enabled = state.scanStatus == "running") {
                    Text("Pause")
                }
                Button(onClick = onResumeScan, enabled = state.scanStatus == "paused") {
                    Text("Resume")
                }
                Button(
                    onClick = onCancelScan,
                    enabled = state.scanStatus in setOf("running", "paused", "queued", "in_progress"),
                ) {
                    Text("Cancel")
                }
            }
        }
    }
}

@Composable
private fun MapListScreen(
    title: String,
    items: List<Map<String, Any>>,
    subtitle: String? = null,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(title, style = MaterialTheme.typography.headlineMedium)
        if (!subtitle.isNullOrBlank()) {
            Text(subtitle)
        }

        if (items.isEmpty()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "No data available in local runtime.",
                    modifier = Modifier.padding(12.dp),
                )
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(items) { item ->
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            item.entries.take(10).forEach { entry ->
                                Text("${entry.key}: ${entry.value}")
                            }
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(4.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) {
                Text("Dashboard")
            }
            Button(onClick = { onNavigate(AppDestination.Settings) }) {
                Text("Settings")
            }
        }
    }
}

@Composable
private fun TagScreen(
    tags: List<String>,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Tags", style = MaterialTheme.typography.headlineMedium)

        if (tags.isEmpty()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "No tags available in local runtime.",
                    modifier = Modifier.padding(12.dp),
                )
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(tags) { tag ->
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Text(
                            text = tag,
                            modifier = Modifier.padding(12.dp),
                        )
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(4.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) {
                Text("Dashboard")
            }
            Button(onClick = { onNavigate(AppDestination.Settings) }) {
                Text("Settings")
            }
        }
    }
}

@Composable
private fun DataOverviewScreen(
    title: String,
    lines: List<String>,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(title, style = MaterialTheme.typography.headlineMedium)

        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(lines) { line ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = line,
                        modifier = Modifier.padding(12.dp),
                    )
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) {
                Text("Dashboard")
            }
            Button(onClick = { onNavigate(AppDestination.Settings) }) {
                Text("Settings")
            }
        }
    }
}

@Composable
private fun FileManagerScreen(
    state: AppUiState,
    onPreview: (Map<String, Any>) -> Unit,
    onExecute: (Map<String, Any>) -> Unit,
    onUndo: () -> Unit,
    onClear: () -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    var action by rememberSaveable { mutableStateOf("batch_move") }
    var selectedImageIds by rememberSaveable { mutableStateOf(setOf<Int>()) }
    var selectedFolderUri by rememberSaveable { mutableStateOf("") }
    var targetFolderUri by rememberSaveable { mutableStateOf("") }
    var name by rememberSaveable { mutableStateOf("") }
    var pattern by rememberSaveable { mutableStateOf("renamed_{n}") }
    var folderName by rememberSaveable { mutableStateOf("") }
    var conflictMode by rememberSaveable { mutableStateOf("rename") }
    var actionMenuExpanded by rememberSaveable { mutableStateOf(false) }
    var targetFolderMenuExpanded by rememberSaveable { mutableStateOf(false) }
    var conflictMenuExpanded by rememberSaveable { mutableStateOf(false) }

    val actionOptions = listOf(
        "rename_image" to "Rename Image",
        "batch_rename_images" to "Batch Rename Images",
        "rename_folder" to "Rename Folder",
        "create_folder" to "Create Folder",
        "delete_folder" to "Delete Folder",
        "delete_images" to "Delete Images",
        "move_images" to "Move Images",
        "copy_images" to "Copy Images",
        "batch_move" to "Batch Move",
        "batch_copy" to "Batch Copy",
        "batch_delete" to "Batch Delete",
    )

    val folderRows = state.libraryFolders
        .sortedBy { it["folder_uri"]?.toString().orEmpty() }
    val imageRows = state.images
    val selectedFolder = selectedFolderUri.ifBlank { null }
    val shownImages = if (selectedFolder == null) {
        imageRows
    } else {
        imageRows.filter { it.folderUriValue() == selectedFolder }
    }

    val selectedIdsCsv = selectedImageIds.joinToString(",")
    val targetFolder = when {
        targetFolderUri.isNotBlank() -> targetFolderUri
        selectedFolder != null -> selectedFolder
        else -> ""
    }

    val needsImageSelection = action in setOf(
        "rename_image",
        "batch_rename_images",
        "delete_images",
        "batch_delete",
        "move_images",
        "copy_images",
        "batch_move",
        "batch_copy",
    )
    val needsSingleImage = action == "rename_image"
    val needsFolderSelection = action in setOf("rename_folder", "delete_folder")
    val needsTargetFolder = action in setOf("create_folder", "move_images", "copy_images", "batch_move", "batch_copy")
    val needsFolderName = action in setOf("create_folder", "rename_folder")
    val needsImageName = action == "rename_image"
    val needsPattern = action == "batch_rename_images"

    val validationMessage = when {
        needsSingleImage && selectedImageIds.size != 1 -> "Select exactly one image for Rename Image."
        needsImageSelection && selectedImageIds.isEmpty() -> "Select one or more images."
        needsFolderSelection && selectedFolder == null -> "Select a folder in the left panel."
        needsTargetFolder && targetFolder.isBlank() -> "Select a target folder."
        needsImageName && name.isBlank() -> "Image new name is required."
        needsPattern && pattern.isBlank() -> "Batch rename pattern is required."
        needsFolderName && folderName.isBlank() -> "Folder name is required."
        else -> null
    }

    fun buildPayload(): Map<String, Any> {
        val payload = mutableMapOf<String, Any>(
            "action" to action,
            "conflict_mode" to conflictMode,
        )
        if (needsImageSelection && selectedIdsCsv.isNotBlank()) payload["image_ids"] = selectedIdsCsv
        if (action in setOf("rename_folder", "delete_folder") && selectedFolder != null) payload["source_folder_uri"] = selectedFolder
        if (needsTargetFolder && targetFolder.isNotBlank()) payload["target_folder_uri"] = targetFolder
        if (needsImageName && name.isNotBlank()) payload["name"] = name.trim()
        if (needsPattern && pattern.isNotBlank()) payload["pattern"] = pattern.trim()
        if (needsFolderName && folderName.isNotBlank()) payload["folder_name"] = folderName.trim()
        return payload
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("File Manager", style = MaterialTheme.typography.headlineMedium)
        Text("Select folders and images, then run SAF file operations from the right panel.")

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Card(modifier = Modifier.weight(0.26f).fillMaxHeight()) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("Folders", style = MaterialTheme.typography.titleMedium)
                    Button(
                        onClick = { selectedFolderUri = "" },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(if (selectedFolder == null) "All Folders Selected" else "Clear Folder Selection")
                    }

                    LazyColumn(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        items(folderRows) { folder ->
                            val folderUri = folder["folder_uri"]?.toString().orEmpty()
                            val selected = folderUri == selectedFolder
                            val depth = folderUri.split('/').count { it.isNotBlank() }.coerceAtMost(5)
                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(start = ((depth - 1).coerceAtLeast(0) * 6).dp)
                                    .clickable {
                                        selectedFolderUri = if (selected) "" else folderUri
                                        if (targetFolderUri.isBlank()) {
                                            targetFolderUri = folderUri
                                        }
                                    },
                            ) {
                                Column(modifier = Modifier.padding(8.dp)) {
                                    Text(
                                        if (selected) "[Selected] ${folderLabelFromUri(folderUri)}" else folderLabelFromUri(folderUri),
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    Text(folderUri, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                }
                            }
                        }
                    }
                }
            }

            Card(modifier = Modifier.weight(0.44f).fillMaxHeight()) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("Images", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Selected ${selectedImageIds.size} image(s)${if (selectedFolder != null) " in ${folderLabelFromUri(selectedFolder)}" else ""}",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        AssistChip(
                            onClick = {
                                selectedImageIds = shownImages.mapNotNull { it.imageId() }.toSet()
                            },
                            label = { Text("Select Visible") },
                        )
                        AssistChip(
                            onClick = { selectedImageIds = emptySet() },
                            label = { Text("Clear Selection") },
                        )
                    }

                    if (shownImages.isEmpty()) {
                        Text("No images for current folder selection.")
                    } else {
                        LazyVerticalGrid(
                            columns = GridCells.Adaptive(minSize = 132.dp),
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            contentPadding = PaddingValues(bottom = 8.dp),
                        ) {
                            items(shownImages) { item ->
                                val id = item.imageId()
                                val selected = id != null && selectedImageIds.contains(id)
                                val title = item["filename"]?.toString().orEmpty().ifBlank { "Image" }
                                val thumbnailUrl = item["thumbnail_url"]?.toString()?.takeIf { it.isNotBlank() }
                                    ?: item["file_url"]?.toString()?.takeIf { it.isNotBlank() }
                                Card(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable {
                                            if (id != null) {
                                                selectedImageIds = if (selected) {
                                                    selectedImageIds - id
                                                } else {
                                                    selectedImageIds + id
                                                }
                                            }
                                        },
                                ) {
                                    Column(
                                        modifier = Modifier.padding(8.dp),
                                        verticalArrangement = Arrangement.spacedBy(4.dp),
                                    ) {
                                        if (!thumbnailUrl.isNullOrBlank()) {
                                            ImageTile(
                                                model = thumbnailUrl,
                                                contentDescription = title,
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .height(96.dp),
                                                contentScale = ContentScale.Crop,
                                            )
                                        }
                                        Text(title, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                        Text("ID ${id ?: 0}", style = MaterialTheme.typography.bodySmall)
                                        if (selected) {
                                            Text("Selected", style = MaterialTheme.typography.bodySmall)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Card(modifier = Modifier.weight(0.30f).fillMaxHeight()) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("Operations", style = MaterialTheme.typography.titleMedium)
                    Box {
                        Button(onClick = { actionMenuExpanded = true }, modifier = Modifier.fillMaxWidth()) {
                            Text(actionOptions.firstOrNull { it.first == action }?.second ?: action)
                        }
                        DropdownMenu(expanded = actionMenuExpanded, onDismissRequest = { actionMenuExpanded = false }) {
                            actionOptions.forEach { (value, label) ->
                                DropdownMenuItem(
                                    text = { Text(label) },
                                    onClick = {
                                        action = value
                                        actionMenuExpanded = false
                                    },
                                )
                            }
                        }
                    }

                    if (needsTargetFolder) {
                        Box {
                            Button(onClick = { targetFolderMenuExpanded = true }, modifier = Modifier.fillMaxWidth()) {
                                Text(
                                    if (targetFolder.isBlank()) {
                                        "Select Target Folder"
                                    } else {
                                        "Target: ${folderLabelFromUri(targetFolder)}"
                                    },
                                )
                            }
                            DropdownMenu(expanded = targetFolderMenuExpanded, onDismissRequest = { targetFolderMenuExpanded = false }) {
                                folderRows.forEach { folder ->
                                    val folderUri = folder["folder_uri"]?.toString().orEmpty()
                                    DropdownMenuItem(
                                        text = { Text(folderLabelFromUri(folderUri)) },
                                        onClick = {
                                            targetFolderUri = folderUri
                                            targetFolderMenuExpanded = false
                                        },
                                    )
                                }
                            }
                        }
                    }

                    if (needsImageName) {
                        OutlinedTextField(
                            value = name,
                            onValueChange = { name = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("Image new name") },
                        )
                    }
                    if (needsPattern) {
                        OutlinedTextField(
                            value = pattern,
                            onValueChange = { pattern = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("Batch rename pattern") },
                        )
                    }
                    if (needsFolderName) {
                        OutlinedTextField(
                            value = folderName,
                            onValueChange = { folderName = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = {
                                Text(
                                    if (action == "rename_folder") "Folder new name" else "Folder name",
                                )
                            },
                        )
                    }

                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("Conflict")
                        Box {
                            Button(onClick = { conflictMenuExpanded = true }) {
                                Text(
                                    when (conflictMode) {
                                        "overwrite" -> "Overwrite"
                                        "skip" -> "Skip"
                                        else -> "Keep both"
                                    },
                                )
                            }
                            DropdownMenu(expanded = conflictMenuExpanded, onDismissRequest = { conflictMenuExpanded = false }) {
                                listOf(
                                    "rename" to "Keep both",
                                    "overwrite" to "Overwrite",
                                    "skip" to "Skip",
                                ).forEach { (mode, label) ->
                                    DropdownMenuItem(
                                        text = { Text(label) },
                                        onClick = {
                                            conflictMode = mode
                                            conflictMenuExpanded = false
                                        },
                                    )
                                }
                            }
                        }
                    }

                    if (validationMessage != null) {
                        Text(validationMessage, style = MaterialTheme.typography.bodySmall)
                    }

                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Button(
                            onClick = { onPreview(buildPayload()) },
                            enabled = validationMessage == null && !state.fileOperationRunning,
                        ) { Text("Preview") }
                        Button(
                            onClick = { onExecute(buildPayload()) },
                            enabled = validationMessage == null && !state.fileOperationRunning,
                        ) { Text("Execute") }
                        Button(onClick = onUndo, enabled = state.fileOperationUndoAvailable && !state.fileOperationRunning) { Text("Undo") }
                        Button(onClick = onClear) { Text("Clear") }
                    }

                    LinearProgressIndicator(
                        progress = state.fileOperationProgress.toFloat().coerceIn(0f, 1f),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Text("${(state.fileOperationProgress * 100.0).toInt()}%")

                    if (state.fileOperationPreview.isNotEmpty()) {
                        Text("Pending", style = MaterialTheme.typography.titleMedium)
                        LazyColumn(modifier = Modifier.heightIn(max = 140.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            items(state.fileOperationPreview) { row ->
                                Card(modifier = Modifier.fillMaxWidth()) {
                                    Column(modifier = Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                        Text("#${row["index"]} ${row["action"]}")
                                        Text("id=${row["image_id"]} conflict=${row["conflict"]}")
                                    }
                                }
                            }
                        }
                    }

                    if (state.fileOperationResults.isNotEmpty()) {
                        Text("Results", style = MaterialTheme.typography.titleMedium)
                        LazyColumn(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            items(state.fileOperationResults) { row ->
                                Card(modifier = Modifier.fillMaxWidth()) {
                                    Column(modifier = Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                        Text("${if (row["ok"] == true) "PASS" else "FAIL"} ${row["action"]}")
                                        row.entries.take(5).forEach { (k, v) ->
                                            Text("$k=$v", style = MaterialTheme.typography.bodySmall)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        if (state.lastActionMessage != null) {
            Text(state.lastActionMessage)
        }
        if (state.errorMessage != null) {
            Text("Error: ${state.errorMessage}")
        }

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = { onNavigate(AppDestination.LibraryBrowser) }) { Text("Library") }
            Button(onClick = { onNavigate(AppDestination.FolderBrowser) }) { Text("Folder Browser") }
            Button(onClick = { onNavigate(AppDestination.Dashboard) }) { Text("Dashboard") }
        }
    }
}

private fun Map<String, Any>.imageId(): Int? {
    val raw = this["image_id"]
    return when (raw) {
        is Number -> raw.toInt()
        is String -> raw.toIntOrNull()
        else -> null
    }
}

private fun Map<String, Any>.folderUriValue(): String {
    val raw = this["folder_uri"]?.toString().orEmpty()
    if (raw.isNotBlank()) {
        return raw
    }
    return this["parent_uri"]?.toString().orEmpty()
}

private fun folderLabelFromUri(uri: String): String {
    if (uri.isBlank()) {
        return "(none)"
    }
    val normalized = uri.trimEnd('/')
    val segment = normalized.substringAfterLast('/')
    if (segment.isNotBlank()) {
        return segment
    }
    return normalized
}

private fun Map<String, Any>.favoriteFlag(): Boolean {
    val top = this["favorite"]
    if (top is Boolean) {
        return top
    }
    if (top is Number) {
        return top.toInt() != 0
    }
    val metadata = this["metadata"] as? Map<*, *> ?: return false
    val nested = metadata["favorite"]
    return when (nested) {
        is Boolean -> nested
        is Number -> nested.toInt() != 0
        is String -> nested.equals("true", ignoreCase = true) || nested == "1"
        else -> false
    }
}

private fun Map<String, Any>.ratingValue(): Int {
    val top = this["rating"]
    if (top is Number) {
        return top.toInt()
    }
    if (top is String) {
        return top.toIntOrNull() ?: 0
    }
    val metadata = this["metadata"] as? Map<*, *> ?: return 0
    val nested = metadata["rating"]
    return when (nested) {
        is Number -> nested.toInt()
        is String -> nested.toIntOrNull() ?: 0
        else -> 0
    }
}

private fun metadataRows(selected: Map<String, Any>): List<String> {
    val lines = mutableListOf<String>()
    val metadata = selected["metadata"] as? Map<*, *> ?: emptyMap<String, Any>()
    val tags = when (val nested = metadata["tags"]) {
        is List<*> -> nested.mapNotNull { it?.toString()?.trim() }.filter { it.isNotBlank() }
        is String -> nested.split('|').map { it.trim() }.filter { it.isNotBlank() }
        else -> emptyList()
    }
    lines += "Filename: ${selected["filename"]?.toString().orEmpty().ifBlank { "n/a" }}"
    lines += "Image ID: ${selected["image_id"] ?: "n/a"}"
    lines += "Width: ${metadata["width"] ?: "n/a"}"
    lines += "Height: ${metadata["height"] ?: "n/a"}"
    lines += "Resolution: ${metadata["resolution"] ?: "n/a"}"
    lines += "Aspect ratio: ${metadata["aspect_ratio"] ?: "n/a"}"
    lines += "Orientation: ${metadata["orientation"] ?: "n/a"}"
    lines += "Extension: ${selected["format"] ?: metadata["format"] ?: "n/a"}"
    lines += "File size: ${humanBytes(metadata["size_bytes"].asLongNullable() ?: 0L)}"
    lines += "Modified date: ${formatTimestamp(metadata["modified_at_ms"] ?: metadata["last_modified_ms"])}"
    lines += "Indexed date: ${formatTimestamp(metadata["date_indexed_ms"])}"
    lines += "Folder: ${displayFolderName(metadata)}"
    lines += "Favorite: ${if (selected.favoriteFlag()) "yes" else "no"}"
    lines += "Rating: ${selected.ratingValue()}"
    lines += "Tags: ${tags.joinToString(separator = ", ") { it }.ifBlank { "none" }}"
    return lines
}

private fun displayFolderName(metadata: Map<*, *>): String {
    val raw = metadata["folder_name"]?.toString()
        ?: metadata["folder_uri"]?.toString()
        ?: metadata["scan_source"]?.toString()
        ?: return "n/a"
    val decoded = Uri.decode(raw).trim()
    val segment = decoded
        .substringAfterLast('/')
        .substringAfterLast(':')
        .substringBefore('?')
        .substringBefore('#')
        .trim()
    return segment.ifBlank { "n/a" }
}

private fun formatTimestamp(value: Any?): String {
    val raw = value.asLongNullable() ?: return "n/a"
    return try {
        val sdf = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US)
        sdf.format(Date(raw))
    } catch (_: Exception) {
        "n/a"
    }
}

@Composable
private fun ImageTile(
    model: Any?,
    contentDescription: String,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Crop,
) {
    val context = LocalContext.current
    val imageLoader = remember(context) {
        ImageLoader.Builder(context)
            .components { add(GifDecoder.Factory()) }
            .build()
    }
    AsyncImage(
        model = model,
        contentDescription = contentDescription,
        imageLoader = imageLoader,
        modifier = modifier,
        contentScale = contentScale,
    )
}
