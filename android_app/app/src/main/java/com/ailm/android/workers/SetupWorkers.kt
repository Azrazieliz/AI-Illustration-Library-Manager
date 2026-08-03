package com.ailm.android.workers

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.ailm.android.runtime.StandaloneRuntime
import com.ailm.android.startup.AppBootstrap

class InitialSetupWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        return runCatching {
            AppBootstrap.initializeRuntime(applicationContext)
            StandaloneRuntime.detectAiHardwareProfile()
            StandaloneRuntime.validateLocalAiInfrastructure()
            StandaloneRuntime.resumeAiQueue()
            Result.success()
        }.getOrElse {
            Result.retry()
        }
    }
}

class ModelDownloadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        return runCatching {
            AppBootstrap.initializeRuntime(applicationContext)
            StandaloneRuntime.resumeAiQueue()
            Result.success()
        }.getOrElse {
            Result.retry()
        }
    }
}
