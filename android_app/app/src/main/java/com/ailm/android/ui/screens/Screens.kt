package com.ailm.android.ui.screens

import androidx.compose.foundation.Image
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import coil.compose.rememberAsyncImagePainter
import com.ailm.android.ui.navigation.AppDestination
import com.ailm.android.ui.viewmodel.AppViewModel

@Composable
fun ScreenScaffold(
    destination: AppDestination,
    onNavigate: (AppDestination) -> Unit,
    appViewModel: AppViewModel,
) {
    val state by appViewModel.uiState.collectAsState()

    if (state.health.isEmpty()) {
        appViewModel.refreshDashboard()
    }

    when (destination) {
        AppDestination.Splash -> GenericScreen("Splash Screen", listOf("Startup diagnostics", "Health checks"), onNavigate)
        AppDestination.FirstLaunchWizard -> GenericScreen("First Launch Wizard", listOf("Resumable guided setup", "WorkManager orchestration"), onNavigate)
        AppDestination.Dashboard -> DashboardScreen(state.stats, state.health, onNavigate)
        AppDestination.LibraryBrowser -> GenericScreen("Library Browser", listOf("Thumbnails", "Lazy loading", "Pagination", "Multi-selection", "Drag selection", "Filters", "Sorting", "Folder tree"), onNavigate)
        AppDestination.FolderBrowser -> GenericScreen("Folder Browser", listOf("SAF", "Tree URI", "DocumentProvider"), onNavigate)
        AppDestination.ImageViewer -> ImageViewerScreen()
        AppDestination.RecognitionResults -> GenericScreen("Recognition Results", listOf("Model confidence", "Review actions"), onNavigate)
        AppDestination.ReviewQueue -> GenericScreen("Review Queue", listOf("Approve", "Reject", "Edit", "Bulk approve", "Bulk reject", "Undo"), onNavigate)
        AppDestination.Search -> GenericScreen("Search", listOf("Filename", "Tags", "Characters", "Series", "Collections"), onNavigate)
        AppDestination.AdvancedSearch -> GenericScreen("Advanced Search", listOf("Hybrid search", "Scoped filters"), onNavigate)
        AppDestination.SemanticSearch -> GenericScreen("Semantic Search", listOf("Embedding search", "Similarity threshold"), onNavigate)
        AppDestination.CharacterPage -> GenericScreen("Character Page", listOf("Character profile", "Aliases", "Relationships"), onNavigate)
        AppDestination.SeriesPage -> GenericScreen("Series Page", listOf("Series metadata", "Related characters"), onNavigate)
        AppDestination.Collections -> GenericScreen("Collections", listOf("Collection browser", "Bulk tagging"), onNavigate)
        AppDestination.Tags -> GenericScreen("Tags", listOf("Tag hierarchy", "Bulk assign/remove"), onNavigate)
        AppDestination.BulkOperations -> GenericScreen("Bulk Operations", listOf("Rename", "Organize", "Copy", "Move", "Delete"), onNavigate)
        AppDestination.KnowledgePacks -> GenericScreen("Knowledge Packs", listOf("Installed/downloadable", "Updates", "Enable/disable", "Uninstall", "Priorities", "Integrity", "Storage usage"), onNavigate)
        AppDestination.Downloads -> GenericScreen("Downloads", listOf("Pause", "Resume", "Retry", "Checksum verification"), onNavigate)
        AppDestination.Automation -> GenericScreen("Automation", listOf("Background scheduling", "Battery-aware jobs"), onNavigate)
        AppDestination.PluginManager -> GenericScreen("Plugin Manager", listOf("Install", "Enable", "Disable", "Update"), onNavigate)
        AppDestination.Statistics -> GenericScreen("Statistics", listOf("Performance", "Caches", "Memory trimming"), onNavigate)
        AppDestination.Logs -> GenericScreen("Logs", listOf("Operational logs", "Diagnostics export"), onNavigate)
        AppDestination.Settings -> GenericScreen("Settings", listOf("Recognition", "Performance", "Storage", "Automation", "Knowledge Packs", "Plugins", "Appearance", "Updates", "Diagnostics"), onNavigate)
        AppDestination.About -> GenericScreen("About", listOf("Version 2.0.0", "Stable channel", "Release metadata"), onNavigate)
    }
}

@Composable
private fun DashboardScreen(
    stats: Map<String, Any>,
    health: Map<String, Any>,
    onNavigate: (AppDestination) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Dashboard", style = MaterialTheme.typography.headlineMedium)
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text("Health: ${health["healthy"] ?: "unknown"}")
                Text("Total images: ${stats["total_images"] ?: 0}")
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            AppDestination.entries.filter { it != AppDestination.Splash }.take(6).forEach { destination ->
                AssistChip(onClick = { onNavigate(destination) }, label = { Text(destination.title) })
            }
        }
    }
}

@Composable
private fun ImageViewerScreen() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Image Viewer", style = MaterialTheme.typography.headlineSmall)
        Image(
            painter = rememberAsyncImagePainter("https://example.invalid/thumbnail.jpg"),
            contentDescription = "thumbnail-preview",
            modifier = Modifier
                .fillMaxWidth()
                .height(240.dp),
        )
        Text("Coil-backed previews with lazy paging and cache-aware rendering.")
    }
}

@Composable
private fun GenericScreen(
    title: String,
    capabilities: List<String>,
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
            items(capabilities) { item ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = item,
                        modifier = Modifier.padding(12.dp),
                    )
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
