package com.ailm.android.startup

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.ailm.android.runtime.StandaloneRuntime
import com.ailm.android.workers.InitialSetupWorker

object AppBootstrap {
    @Volatile
    private var runtimeInitialized = false

    @Volatile
    private var workersRegistered = false

    fun initializeApplication(context: Context) {
        val appContext = context.applicationContext
        // Initialize runtime and register workers asynchronously so application
        // startup and the splash screen are not blocked by heavy init work.
        val executor = java.util.concurrent.Executors.newSingleThreadExecutor()
        executor.execute {
            try {
                initializeRuntime(appContext)
                registerStartupWorkers(appContext)
            } finally {
                // notify listeners even if startup initialization fails
                notifyInitializationListeners()
                // shut down executor after tasks complete
                try { executor.shutdown() } catch (_: Throwable) {}
            }
        }
    }

    private val initListeners = mutableListOf<() -> Unit>()

    fun isRuntimeInitialized(): Boolean {
        return runtimeInitialized
    }

    fun addInitializationListener(listener: () -> Unit) {
        val shouldPostImmediately = synchronized(initListeners) {
            if (runtimeInitialized) {
                true
            } else {
                initListeners.add(listener)
                false
            }
        }
        if (shouldPostImmediately) {
            Handler(Looper.getMainLooper()).post { listener() }
        }
    }

    private fun notifyInitializationListeners() {
        val toNotify = synchronized(initListeners) {
            val copy = initListeners.toList()
            initListeners.clear()
            copy
        }
        val handler = Handler(Looper.getMainLooper())
        toNotify.forEach { listener ->
            handler.post { listener() }
        }
    }

    private fun initializeRuntime(context: Context) {
        if (runtimeInitialized) {
            return
        }
        synchronized(this) {
            if (runtimeInitialized) {
                return
            }
            StandaloneRuntime.initialize(context.applicationContext)
            runtimeInitialized = true
        }
    }

    private fun registerStartupWorkers(context: Context) {
        if (workersRegistered) {
            return
        }
        synchronized(this) {
            if (workersRegistered) {
                return
            }

            val appContext = context.applicationContext
            val initialSetupRequest = OneTimeWorkRequestBuilder<InitialSetupWorker>()
                .addTag(INITIAL_SETUP_WORK_TAG)
                .build()
            WorkManager.getInstance(appContext).enqueueUniqueWork(
                INITIAL_SETUP_WORK_NAME,
                ExistingWorkPolicy.KEEP,
                initialSetupRequest,
            )
            workersRegistered = true
        }
    }

    private const val INITIAL_SETUP_WORK_NAME = "ailm.initial.setup"
    private const val INITIAL_SETUP_WORK_TAG = "ailm_initial_setup"
}
