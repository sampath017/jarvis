package com.jarvis.edge.sync

import android.content.Context
import androidx.work.*
import com.google.firebase.auth.FirebaseAuth
import com.jarvis.edge.data.local.OutboxDatabase
import com.jarvis.edge.data.remote.JarvisApi
import kotlinx.coroutines.tasks.await
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

class SyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    private val db = OutboxDatabase.getDatabase(context)
    private val api: JarvisApi

    init {
        // Construct API client.
        // Replace with your Cloud Run service URL or configure via settings.
        val baseUrl = "https://jarvis-api-898516599131.asia-south1.run.app/" 
        
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }
        val okHttpClient = OkHttpClient.Builder()
            .addInterceptor(logging)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()

        api = retrofit.create(JarvisApi::class.java)
    }

    override suspend fun doWork(): androidx.work.ListenableWorker.Result {
        try {
            val events = db.outboxDao().getAllEvents()
            if (events.isEmpty()) return androidx.work.ListenableWorker.Result.success()

            // Retrieve Firebase token
            val user = FirebaseAuth.getInstance().currentUser
            if (user == null) {
                // Not signed in; wait for auth before syncing
                return androidx.work.ListenableWorker.Result.failure()
            }

            // Await token retrieval
            val tokenResult = user.getIdToken(false).await()
            val token = "Bearer ${tokenResult.token}"

            // Await App Check token if available
            val appCheckToken = getAppCheckToken()

            var success = true
            for (event in events) {
                val req = event.toRequest()
                val response = api.sendContextEvent(token, appCheckToken, req)
                
                if (response.isSuccessful && response.body()?.status == "ok") {
                    db.outboxDao().deleteEventById(event.eventId)
                } else {
                    success = false
                }
            }

            return if (success) {
                androidx.work.ListenableWorker.Result.success()
            } else {
                androidx.work.ListenableWorker.Result.retry()
            }
        } catch (e: Exception) {
            return androidx.work.ListenableWorker.Result.retry()
        }
    }

    private suspend fun getAppCheckToken(): String? {
        return try {
            val appCheck = com.google.firebase.appcheck.FirebaseAppCheck.getInstance()
            val result = appCheck.getToken(false).await()
            result.token
        } catch (e: Exception) {
            null
        }
    }

    companion object {
        private const val SYNC_WORK_NAME = "jarvis_sync_work"

        fun enqueueSync(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val workRequest = OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(constraints)
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    10000L, // 10s (equivalent to WorkRequest.MIN_BACKOFF_MILLIS)
                    TimeUnit.MILLISECONDS
                )
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                SYNC_WORK_NAME,
                ExistingWorkPolicy.APPEND_OR_REPLACE,
                workRequest
            )
        }
    }
}
