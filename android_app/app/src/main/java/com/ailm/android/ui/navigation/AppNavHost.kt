package com.ailm.android.ui.navigation

import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.ailm.android.ui.screens.ScreenScaffold
import com.ailm.android.ui.viewmodel.AppViewModel

@Composable
fun AppNavHost(appViewModel: AppViewModel = viewModel()) {
    val navController = rememberNavController()
    NavHost(navController = navController, startDestination = AppDestination.FirstLaunchWizard.route) {
        AppDestination.entries.forEach { destination ->
            composable(destination.route) {
                ScreenScaffold(
                    destination = destination,
                    onNavigate = { next -> navController.navigate(next.route) },
                    appViewModel = appViewModel,
                )
            }
        }
    }
}
