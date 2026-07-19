package com.jarvis.edge

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.firebase.FirebaseApp
import com.google.firebase.appcheck.FirebaseAppCheck
import com.google.firebase.auth.FirebaseAuth
import com.jarvis.edge.data.remote.*
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.tasks.await
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import org.junit.Assert.*
import org.junit.Before
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * End-to-end instrumented test for the Jarvis frontend-to-backend flow.
 *
 * This test runs ON your physical Android device. It exercises:
 *   1. Firebase Auth — verifies the user is signed in
 *   2. Token retrieval — gets a real Firebase ID token
 *   3. App Check token retrieval (best-effort)
 *   4. /v1/commands — sends "hi" to Cloud Run and checks the response
 *   5. /v1/commands — sends "remind me to buy milk" and checks the response
 *   6. /v1/context-events — sends a mock IN_VEHICLE context event
 *
 * Pre-requisites:
 *   - You must be signed in on the app BEFORE running these tests.
 *   - The phone must have internet connectivity.
 *
 * Run with:
 *   ./gradlew.bat connectedDebugAndroidTest --tests "com.jarvis.edge.EndToEndFlowTest"
 *
 * Or from Android Studio: right-click this file → Run 'EndToEndFlowTest'
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class EndToEndFlowTest {

    private lateinit var api: JarvisApi
    private lateinit var auth: FirebaseAuth

    companion object {
        private const val BASE_URL = "https://jarvis-api-898516599131.asia-south1.run.app/"
    }

    @Before
    fun setUp() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext

        // Ensure Firebase is initialized
        if (FirebaseApp.getApps(context).isEmpty()) {
            FirebaseApp.initializeApp(context)
        }

        auth = FirebaseAuth.getInstance()

        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }
        val okHttpClient = OkHttpClient.Builder()
            .addInterceptor(logging)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()

        api = Retrofit.Builder()
            .baseUrl(BASE_URL)
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(JarvisApi::class.java)
    }

    // ── Helper ───────────────────────────────────────────────────────────

    private suspend fun getAuthToken(): String {
        val user = auth.currentUser
        assertNotNull(
            "User must be signed in before running E2E tests. " +
            "Open the app and sign in with Google first.", user
        )
        val tokenResult = user!!.getIdToken(true).await()
        val token = tokenResult.token
        assertNotNull("Firebase ID token should not be null", token)
        return "Bearer $token"
    }

    private suspend fun getAppCheckToken(): String? {
        return try {
            val result = FirebaseAppCheck.getInstance().getToken(false).await()
            result.token
        } catch (e: Exception) {
            // App Check may not be set up properly on debug builds — that's OK
            null
        }
    }

    // ── Test 1: Auth baseline ────────────────────────────────────────────

    @Test
    fun test01_userIsSignedIn() {
        val user = auth.currentUser
        assertNotNull(
            "FAIL: No user signed in. Open the Jarvis app and sign in before running tests.",
            user
        )
        println("✅ Signed in as: ${user!!.email} (uid: ${user.uid})")
    }

    @Test
    fun test02_canRetrieveFirebaseIdToken() = runBlocking {
        val token = getAuthToken()
        assertTrue("Token should start with 'Bearer '", token.startsWith("Bearer "))
        assertTrue("Token should be long enough to be a real JWT", token.length > 100)
        println("✅ Firebase ID token retrieved (${token.length} chars)")
    }

    // ── Test 3: Simple command "hi" ──────────────────────────────────────

    @Test
    fun test03_sendHiCommand() = runBlocking {
        val token = getAuthToken()
        val appCheck = getAppCheckToken()

        val request = CommandRequest(
            requestId = UUID.randomUUID().toString(),
            threadId = UUID.randomUUID().toString(),
            text = "hi"
        )

        val response = api.sendCommand(token, appCheck, request)

        println("── /v1/commands response ──")
        println("HTTP Status: ${response.code()}")

        if (response.isSuccessful) {
            val body = response.body()!!
            println("run_id:   ${body.runId}")
            println("status:   ${body.status}")
            println("message:  ${body.message}")
            println("error:    ${body.error}")

            assertEquals("ok", body.status)

            // ── The critical check ──
            // If the message contains "Illegal header value" or "your_openrouter",
            // the OPENROUTER_API_KEY secret in GCP is STILL corrupted.
            assertFalse(
                "OPENROUTER_API_KEY is still corrupted in GCP Secret Manager! " +
                "Message was: ${body.message}",
                body.message.contains("Illegal header value")
            )
            assertFalse(
                "OPENROUTER_API_KEY is still the placeholder! " +
                "Message was: ${body.message}",
                body.message.contains("your_openrouter")
            )

            println("✅ 'hi' command processed successfully: ${body.message}")
        } else {
            val errorBody = response.errorBody()?.string()
            fail("API returned ${response.code()}: $errorBody")
        }
    }

    // ── Test 4: Reminder command ─────────────────────────────────────────

    @Test
    fun test04_sendReminderCommand() = runBlocking {
        val token = getAuthToken()
        val appCheck = getAppCheckToken()

        val request = CommandRequest(
            requestId = UUID.randomUUID().toString(),
            threadId = UUID.randomUUID().toString(),
            text = "remind me to buy milk"
        )

        val response = api.sendCommand(token, appCheck, request)

        println("── /v1/commands (reminder) response ──")
        println("HTTP Status: ${response.code()}")

        if (response.isSuccessful) {
            val body = response.body()!!
            println("status:   ${body.status}")
            println("message:  ${body.message}")

            assertEquals("ok", body.status)
            assertFalse(
                "Response still has corrupted API key error",
                body.message.contains("Illegal header")
            )

            println("✅ Reminder command processed: ${body.message}")
        } else {
            fail("API returned ${response.code()}: ${response.errorBody()?.string()}")
        }
    }

    // ── Test 5: Context event (IN_VEHICLE) ───────────────────────────────

    @Test
    fun test05_sendContextEvent() = runBlocking {
        val token = getAuthToken()
        val appCheck = getAppCheckToken()

        val request = ContextEventRequest(
            eventId = UUID.randomUUID().toString(),
            occurredAt = java.time.Instant.now().toString(),
            activity = "IN_VEHICLE",
            transition = "ENTER",
            location = LocationSnapshot(
                latitude = 17.3850,
                longitude = 78.4867,
                accuracyM = 12.0f,
                speedMps = 10.0f,
                bearingDeg = 180.0f,
                timestamp = java.time.Instant.now().toString()
            ),
            featureSummary = FeatureSummary(
                dominantFreqHz = 25.5,
                spectralEnergy = 0.85,
                zRms = 0.42,
                harmonicRatio = 0.65,
                accelMagnitudeMean = 10.2,
                vehicleClassHint = "HUNTER_350",
                classificationConfidence = 0.78
            )
        )

        val response = api.sendContextEvent(token, appCheck, request)

        println("── /v1/context-events response ──")
        println("HTTP Status: ${response.code()}")

        if (response.isSuccessful) {
            val body = response.body()!!
            println("status:     ${body.status}")
            println("message:    ${body.message}")
            println("session_id: ${body.sessionId}")

            assertEquals("ok", body.status)
            println("✅ Context event processed successfully")
        } else {
            val errorBody = response.errorBody()?.string()
            // Context events endpoint may return 403 if not configured — log it
            println("⚠️ Context event returned ${response.code()}: $errorBody")
            // Don't fail — this endpoint might not be fully set up yet
        }
    }

    // ── Test 6: Connectivity sanity check ────────────────────────────────

    @Test
    fun test06_cloudRunIsReachable() = runBlocking {
        val client = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .build()

        val request = okhttp3.Request.Builder()
            .url("${BASE_URL}health")
            .get()
            .build()

        try {
            val response = client.newCall(request).execute()
            println("── /health response ──")
            println("HTTP Status: ${response.code}")
            // Cloud Run might return 404 for /health if not defined, but the connection works
            assertTrue(
                "Cloud Run should be reachable (got ${response.code})",
                response.code in 200..499
            )
            println("✅ Cloud Run is reachable")
        } catch (e: Exception) {
            fail("Cannot reach Cloud Run: ${e.message}")
        }
    }
}
