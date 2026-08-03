package com.ailm.android.ui.screens

import android.content.Context
import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.ailm.android.ui.navigation.AppDestination
import com.ailm.android.ui.viewmodel.AppUiState
import com.ailm.android.ui.viewmodel.AppViewModel

private const val PREFS_NAME = "ailm_android"
private const val PREF_LIBRARY_TREE_URI = "library_tree_uri"

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
            val persistFlags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            runCatching {
                context.contentResolver.takePersistableUriPermission(uri, persistFlags)
            }
            val uriText = uri.toString()
            prefs.edit().putString(PREF_LIBRARY_TREE_URI, uriText).apply()
            appViewModel.setLibraryUri(uriText)
            appViewModel.refreshDashboard()
        }
    }

    LaunchedEffect(Unit) {
        val persistedUri = prefs.getString(PREF_LIBRARY_TREE_URI, null).orEmpty()
        appViewModel.initializeConfiguration(context, persistedUri)
        appViewModel.refreshDashboard()
        appViewModel.refreshScanStatus()
    }

    val chooseFolder: () -> Unit = {
        folderPickerLauncher.launch(null)
    }

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
            images = state.images,
            onOpenImage = {
                appViewModel.selectImage(it)
                onNavigate(AppDestination.ImageViewer)
            },
            onNavigate = onNavigate,
        )

        AppDestination.FolderBrowser -> FolderBrowserScreen(
            state = state,
            onChooseFolder = chooseFolder,
            onStartScan = appViewModel::startScan,
            onRefreshStatus = appViewModel::refreshScanStatus,
            onNavigate = onNavigate,
        )

        AppDestination.ImageViewer -> ImageViewerScreen(
            state = state,
            imageUrl = appViewModel.selectedImageUrl(),
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
            images = state.images,
            onOpenImage = {
                appViewModel.selectImage(it)
                onNavigate(AppDestination.ImageViewer)
            },
            onNavigate = onNavigate,
        )

        AppDestination.AdvancedSearch -> SearchScreen(
            title = "Advanced Search",
            images = state.images,
            onOpenImage = {
                appViewModel.selectImage(it)
                onNavigate(AppDestination.ImageViewer)
            },
            onNavigate = onNavigate,
        )

        AppDestination.SemanticSearch -> SearchScreen(
            title = "Semantic Search",
            images = state.images,
            onOpenImage = {
                appViewModel.selectImage(it)
                onNavigate(AppDestination.ImageViewer)
            },
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

        AppDestination.BulkOperations -> DataOverviewScreen(
            title = "Bulk Operations",
            lines = listOf(
                "Use Search to filter images.",
                "Open image details from Library Browser.",
                "Use Review Queue for manual curation.",
            ),
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

@Composable
private fun SplashScreen(
    state: AppUiState,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("AI Illustration Library Manager", style = MaterialTheme.typography.headlineMedium)
        Text("Backend status: ${state.health["status"] ?: state.health["healthy"] ?: "unknown"}")

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("First Launch Wizard", style = MaterialTheme.typography.headlineMedium)

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
                Text("Health: ${state.health["status"] ?: state.health["healthy"] ?: "unknown"}")
                Text("Runtime: Android standalone")
                Text("Library URI configured: ${if (state.selectedLibraryUri.isBlank()) "no" else "yes"}")
                Text("Total images: ${state.stats["total_images"] ?: state.images.size}")
                Text("Collections: ${state.collections.size}")
                Text("Tags: ${state.tags.size}")
            }
        }

        ScanControlsCard(
            state = state,
            onStartScan = onStartScan,
            onPauseScan = onPauseScan,
            onResumeScan = onResumeScan,
            onCancelScan = onCancelScan,
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
    onStartScan: () -> Unit,
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
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onChooseFolder) {
                        Text(if (state.selectedLibraryUri.isBlank()) "Choose Folder" else "Change Folder")
                    }
                    Button(onClick = onRefreshStatus) {
                        Text("Refresh Status")
                    }
                }
                Button(onClick = onStartScan, enabled = state.selectedLibraryUri.isNotBlank()) {
                    Text("Scan Selected Folder")
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
private fun LibraryBrowserScreen(
    images: List<Map<String, Any>>,
    onOpenImage: (Map<String, Any>) -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Library Browser", style = MaterialTheme.typography.headlineMedium)

        if (images.isEmpty()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "No images found in local runtime storage.",
                    modifier = Modifier.padding(12.dp),
                )
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(
                    items = images,
                    key = { item ->
                        "${item["image_id"] ?: 0}:${item["path"] ?: item.hashCode()}"
                    },
                ) { item ->
                    val title = item["filename"]?.toString().orEmpty().ifBlank { "Untitled image" }
                    val path = item["path"]?.toString().orEmpty()
                    val thumbnailUrl = item["thumbnail_url"]?.toString()?.takeIf { it.isNotBlank() }
                        ?: item["file_url"]?.toString()?.takeIf { it.isNotBlank() }

                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onOpenImage(item) },
                    ) {
                        Column(
                            modifier = Modifier.padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            if (!thumbnailUrl.isNullOrBlank()) {
                                AsyncImage(
                                    model = thumbnailUrl,
                                    contentDescription = title,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(220.dp),
                                    contentScale = ContentScale.Crop,
                                )
                            }
                            Text(title, style = MaterialTheme.typography.titleMedium)
                            if (path.isNotBlank()) {
                                Text(path, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            }
                            Text("Tap to open viewer")
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
            Button(onClick = { onNavigate(AppDestination.Search) }) {
                Text("Search")
            }
        }
    }
}

@Composable
private fun ImageViewerScreen(
    state: AppUiState,
    imageUrl: String?,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Image Viewer", style = MaterialTheme.typography.headlineMedium)

        val selected = state.selectedImage
        if (selected == null) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Text("No image selected. Open an item from Library Browser.", modifier = Modifier.padding(12.dp))
            }
        } else {
            val title = selected["filename"]?.toString().orEmpty().ifBlank { "Untitled image" }
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (!imageUrl.isNullOrBlank()) {
                        AsyncImage(
                            model = imageUrl,
                            contentDescription = title,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(320.dp),
                            contentScale = ContentScale.Fit,
                        )
                    }
                    Text(title, style = MaterialTheme.typography.titleMedium)
                    selected.entries.take(10).forEach { entry ->
                        Text("${entry.key}: ${entry.value}")
                    }
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
    images: List<Map<String, Any>>,
    onOpenImage: (Map<String, Any>) -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    val normalized = query.trim().lowercase()
    val filtered = remember(images, normalized) {
        if (normalized.isBlank()) {
            images.take(200)
        } else {
            images.filter { image ->
                val filename = image["filename"]?.toString().orEmpty().lowercase()
                val path = image["path"]?.toString().orEmpty().lowercase()
                filename.contains(normalized) || path.contains(normalized)
            }.take(200)
        }
    }

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
            label = { Text("Filename or path") },
        )
        Text("Results: ${filtered.size}")

        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(filtered) { item ->
                val caption = item["filename"]?.toString().orEmpty().ifBlank { item["path"]?.toString().orEmpty() }
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onOpenImage(item) },
                ) {
                    Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(caption.ifBlank { "Untitled" })
                        Text(item["path"]?.toString().orEmpty(), maxLines = 2, overflow = TextOverflow.Ellipsis)
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
    onRefresh: () -> Unit,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineMedium)

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
                Button(onClick = onChooseFolder) {
                    Text("Choose / Change Library Folder")
                }
            }
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
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Statistics", style = MaterialTheme.typography.headlineMedium)

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Health: ${state.health["status"] ?: state.health["healthy"] ?: "unknown"}")
                Text("Total images: ${state.stats["total_images"] ?: state.images.size}")
                Text("Folders scanned: ${state.stats["folder_count"] ?: state.collections.size}")
                Text("Current scan status: ${state.scanStatus}")
                Text("Current scan discovered images: ${state.scanDiscoveredImages}")
            }
        }

        MapListScreen(
            title = "Raw statistics",
            items = listOf(state.stats),
            onNavigate = onNavigate,
        )
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
