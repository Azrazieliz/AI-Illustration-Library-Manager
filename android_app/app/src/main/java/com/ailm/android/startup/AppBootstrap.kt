package com.ailm.android.startup

import android.content.Context
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
        initializeRuntime(appContext)
        registerStartupWorkers(appContext)
    }

    fun initializeRuntime(context: Context) {
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

    fun registerStartupWorkers(context: Context) {
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
