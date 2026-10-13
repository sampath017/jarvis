package com.jarvis.jarvis_collector

import android.content.Context
import android.util.Log
import androidx.work.Worker
import androidx.work.WorkerParameters

/** Durable fallback if immediate broadcast capture is interrupted or unavailable. */
class ContextLocationWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        return try {
            val pending = ContextEventQueue.pending(applicationContext)
                .filter { it.optBoolean("location_pending") }
            var retry = false
            for (event in ContextLocationCapture.capture(applicationContext, pending, 15_000)) {
                retry = ContextLocationCapture.finishAttempt(event) || retry
                ContextEventQueue.update(applicationContext, event)
            }
            if (retry) ContextEventQueue.scheduleLocationCapture(applicationContext, delaySeconds = 10)
            ContextEventQueue.scheduleFlush(applicationContext)
            Result.success()
        } catch (error: Exception) {
            Log.w("JarvisLocation", "Location capture retained for retry", error)
            Result.retry()
        }
    }
}
