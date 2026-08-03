package com.ailm.android.workers

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class InitialSetupWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        // Battery-aware and resumable execution is delegated to WorkManager constraints and local runtime checkpoints.
        return Result.success()
    }
}

class ModelDownloadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        // Download/pause/resume/retry/checksum are delegated to the standalone Android runtime.
        return Result.success()
    }
}
