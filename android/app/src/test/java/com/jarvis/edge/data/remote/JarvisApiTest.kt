package com.jarvis.edge.data.remote

import com.google.gson.Gson
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

/**
 * Unit tests for the JarvisApi Retrofit interface.
 *
 * Uses OkHttp MockWebServer to simulate Cloud Run responses locally.
 * No device, no Firebase, no real network required.
 *
 * Run with:  ./gradlew.bat test --tests "com.jarvis.edge.data.remote.JarvisApiTest"
 */
class JarvisApiTest {

    private lateinit var mockServer: MockWebServer
    private lateinit var api: JarvisApi
    private val gson = Gson()

    @Before
    fun setUp() {
        mockServer = MockWebServer()
        mockServer.start()

        api = Retrofit.Builder()
            .baseUrl(mockServer.url("/"))
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(JarvisApi::class.java)
    }

    @After
    fun tearDown() {
        mockServer.shutdown()
    }

    // ── /v1/commands ─────────────────────────────────────────────────────

    @Test
    fun `sendCommand returns success with valid response`() = runTest {
        // Arrange — mock a happy-path 200 response from Cloud Run
        val mockBody = APIResponse(
            runId = "run-001",
            status = "ok",
            message = "I'll remind you to buy milk the next time you're at Big Bazaar.",
            changedRecords = listOf("tasks/abc123"),
            sessionId = null,
            error = null
        )
        mockServer.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(gson.toJson(mockBody))
        )

        // Act
        val request = CommandRequest(
            requestId = "req-001",
            threadId = "thread-001",
            text = "remind me to buy milk"
        )
        val response = api.sendCommand("Bearer fake-token", null, request)

        // Assert — HTTP level
        assertTrue("Response should be successful", response.isSuccessful)
        assertEquals(200, response.code())

        // Assert — body
        val body = response.body()!!
        assertEquals("run-001", body.runId)
        assertEquals("ok", body.status)
        assertTrue(body.message.contains("remind"))
        assertEquals(1, body.changedRecords.size)
        assertNull(body.error)

        // Assert — the request that hit MockWebServer
        val recorded = mockServer.takeRequest()
        assertEquals("POST", recorded.method)
        assertEquals("/v1/commands", recorded.path)
        assertTrue(recorded.getHeader("X-Authorization")!!.startsWith("Bearer"))
    }

    @Test
    fun `sendCommand forwards AppCheck header when present`() = runTest {
        mockServer.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(gson.toJson(APIResponse("r", "ok", "hello")))
        )

        api.sendCommand(
            "Bearer token",
            "appcheck-jwt-token",
            CommandRequest("req-2", "t-2", "hi")
        )

        val recorded = mockServer.takeRequest()
        assertEquals("appcheck-jwt-token", recorded.getHeader("X-Firebase-AppCheck"))
    }

    @Test
    fun `sendCommand handles 401 unauthorized`() = runTest {
        mockServer.enqueue(
            MockResponse()
                .setResponseCode(401)
                .setBody("""{"detail":"Not authenticated"}""")
        )

        val response = api.sendCommand(
            "Bearer expired-token",
            null,
            CommandRequest("req-3", "t-3", "hi")
        )

        assertFalse("Response should NOT be successful", response.isSuccessful)
        assertEquals(401, response.code())
    }

    @Test
    fun `sendCommand handles 500 server error`() = runTest {
        mockServer.enqueue(
            MockResponse()
                .setResponseCode(500)
                .setBody("""{"detail":"Internal Server Error"}""")
        )

        val response = api.sendCommand(
            "Bearer token",
            null,
            CommandRequest("req-4", "t-4", "hi")
        )

        assertFalse(response.isSuccessful)
        assertEquals(500, response.code())
    }

    @Test
    fun `sendCommand parses error field when present`() = runTest {
        val mockBody = APIResponse(
            runId = "run-err",
            status = "error",
            message = "Error processing command: Illegal header value",
            error = "OPENROUTER_API_KEY is corrupted"
        )
        mockServer.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(gson.toJson(mockBody))
        )

        val response = api.sendCommand(
            "Bearer token",
            null,
            CommandRequest("req-5", "t-5", "hello")
        )

        assertTrue(response.isSuccessful)
        val body = response.body()!!
        assertEquals("error", body.status)
        assertNotNull(body.error)
        assertTrue(body.message.contains("Illegal header"))
    }

    // ── /v1/context-events ───────────────────────────────────────────────

    @Test
    fun `sendContextEvent returns success`() = runTest {
        val mockBody = APIResponse(
            runId = "run-ctx-001",
            status = "ok",
            message = "Context event processed",
            sessionId = "session-123"
        )
        mockServer.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(gson.toJson(mockBody))
        )

        val request = ContextEventRequest(
            eventId = "evt-001",
            occurredAt = "2026-07-19T10:00:00Z",
            activity = "IN_VEHICLE",
            transition = "ENTER",
            location = LocationSnapshot(
                latitude = 17.3850,
                longitude = 78.4867,
                accuracyM = 15.0f,
                speedMps = 8.5f,
                bearingDeg = null,
                timestamp = "2026-07-19T10:00:00Z"
            )
        )

        val response = api.sendContextEvent("Bearer token", "appcheck", request)

        assertTrue(response.isSuccessful)
        val body = response.body()!!
        assertEquals("session-123", body.sessionId)
        assertEquals("ok", body.status)

        val recorded = mockServer.takeRequest()
        assertEquals("/v1/context-events", recorded.path)

        // Verify JSON body was serialized correctly
        val sentJson = recorded.body.readUtf8()
        assertTrue(sentJson.contains("\"event_id\":\"evt-001\""))
        assertTrue(sentJson.contains("\"activity\":\"IN_VEHICLE\""))
        assertTrue(sentJson.contains("\"latitude\":17.385"))
    }

    // ── Model serialization ──────────────────────────────────────────────

    @Test
    fun `CommandRequest serializes with snake_case fields`() {
        val req = CommandRequest(
            requestId = "r1",
            threadId = "t1",
            text = "remind me to buy milk",
            currentContextRef = "ctx-ref"
        )
        val json = gson.toJson(req)
        assertTrue(json.contains("\"request_id\""))
        assertTrue(json.contains("\"thread_id\""))
        assertTrue(json.contains("\"current_context_ref\""))
    }

    @Test
    fun `APIResponse deserializes changed_records list`() {
        val json = """
            {
                "run_id": "r1",
                "status": "ok",
                "message": "done",
                "changed_records": ["tasks/a", "tasks/b"],
                "session_id": null,
                "error": null
            }
        """.trimIndent()

        val resp = gson.fromJson(json, APIResponse::class.java)
        assertEquals(2, resp.changedRecords.size)
        assertEquals("tasks/a", resp.changedRecords[0])
    }
}
