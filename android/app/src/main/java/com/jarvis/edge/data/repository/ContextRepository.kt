package com.jarvis.edge.data.repository

import android.content.Context
import com.google.firebase.appcheck.FirebaseAppCheck
import com.google.firebase.auth.FirebaseAuth
import com.jarvis.edge.data.remote.APIResponse
import com.jarvis.edge.data.remote.CommandRequest
import com.jarvis.edge.data.remote.ContextEventRequest
import com.jarvis.edge.data.remote.LocationSnapshot
import com.jarvis.edge.data.remote.JarvisApi
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.TimeUnit

class ContextRepository(private val context: Context) {

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
            .readTimeout(90, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()

        api = retrofit.create(JarvisApi::class.java)
    }

    suspend fun executeCommand(text: String, threadId: String?): Result<APIResponse> {
        val user = FirebaseAuth.getInstance().currentUser
            ?: return Result.failure(Exception("User not authenticated"))

        return try {
            val tokenResult = user.getIdToken(false).await()
            val token = "Bearer ${tokenResult.token}"
            
            val appCheckToken = getAppCheckToken()

            // Best-effort real-time location update before command execution
            try {
                val locationProvider = com.jarvis.edge.domain.sensors.LocationProvider(context)
                val location = withTimeoutOrNull(3000) {
                    locationProvider.getCurrentLocation() ?: locationProvider.getLastLocation()
                }
                if (location != null) {
                    val timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date())
                    val locSnapshot = LocationSnapshot(
                        latitude = location.latitude,
                        longitude = location.longitude,
                        accuracyM = location.accuracy,
                        speedMps = location.speed,
                        bearingDeg = location.bearing,
                        timestamp = timestamp
                    )
                    val ctxReq = ContextEventRequest(
                        eventId = UUID.randomUUID().toString(),
                        occurredAt = timestamp,
                        activity = "STILL",
                        transition = "ENTER",
                        location = locSnapshot
                    )
                    api.sendContextEvent(token, appCheckToken, ctxReq)
                }
            } catch (e: Exception) {
                android.util.Log.w("ContextRepository", "Failed to send real-time location context: ${e.message}")
            }

            val req = CommandRequest(
                requestId = UUID.randomUUID().toString(),
                threadId = threadId ?: UUID.randomUUID().toString(),
                text = text
            )

            val response = api.sendCommand(token, appCheckToken, req)
            if (response.isSuccessful && response.body() != null) {
                Result.success(response.body()!!)
            } else {
                Result.failure(Exception("API returned error code ${response.code()}: ${response.errorBody()?.string()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend fun getAppCheckToken(): String? {
        return try {
            val appCheck = FirebaseAppCheck.getInstance()
            val result = appCheck.getToken(false).await()
            result.token
        } catch (e: Exception) {
            null
        }
    }
}
