package com.jarvis.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jarvis.models.*
import com.jarvis.services.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * Main ViewModel for the Jarvis app.
 * Orchestrates all services and exposes UI state.
 */
class JarvisViewModel(application: Application) : AndroidViewModel(application) {

    val gemmaEngine = GemmaEngine(application)
    val contextManager = ContextManager(application)
    val motionClassifier = MotionClassifier(application)
    val vehicleSessionManager = VehicleSessionManager()
    val memoryStorage = MemoryStorage(application)

    // Chat state
    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages.asStateFlow()

    private val _isProcessing = MutableStateFlow(false)
    val isProcessing: StateFlow<Boolean> = _isProcessing.asStateFlow()

    // Context state
    private val _jarvisContext = MutableStateFlow(JarvisContext())
    val jarvisContext: StateFlow<JarvisContext> = _jarvisContext.asStateFlow()

    // Navigation state
    private val _currentTab = MutableStateFlow(0)
    val currentTab: StateFlow<Int> = _currentTab.asStateFlow()

    // Initialization state
    private val _isInitialized = MutableStateFlow(false)
    val isInitialized: StateFlow<Boolean> = _isInitialized.asStateFlow()

    init {
        viewModelScope.launch {
            initialize()
        }
    }

    private suspend fun initialize() {
        // Load saved chat history
        try {
            memoryStorage.getChatHistoryFlow().collect { history ->
                if (_messages.value.isEmpty() && history.isNotEmpty()) {
                    _messages.value = history
                }
            }
        } catch (_: Exception) {}

        // Load saved known places into context manager
        try {
            val places = memoryStorage.getKnownPlaces()
            places.forEach { place ->
                contextManager.addKnownPlace(
                    id = place.id,
                    label = place.label,
                    latitude = place.latitude,
                    longitude = place.longitude,
                    radiusM = place.radiusM,
                    type = place.type,
                )
            }
        } catch (_: Exception) {}

        _isInitialized.value = true
    }

    fun setCurrentTab(index: Int) {
        _currentTab.value = index
    }

    /**
     * Send a message to Jarvis and get a response.
     */
    fun sendMessage(content: String) {
        if (content.isBlank()) return

        val userMessage = ChatMessage(
            id = UUID.randomUUID().toString(),
            content = content.trim(),
            role = MessageRole.USER,
        )
        _messages.value = _messages.value + userMessage
        _isProcessing.value = true

        viewModelScope.launch {
            val contextSummary = buildContextSummary()
            val prompt = gemmaEngine.buildContextPrompt(content, contextSummary)

            val response = if (gemmaEngine.isModelLoaded.value) {
                gemmaEngine.generateResponse(prompt)
            } else {
                buildOfflineResponse(content)
            }

            val assistantMessage = ChatMessage(
                id = UUID.randomUUID().toString(),
                content = response,
                role = MessageRole.ASSISTANT,
                contextSnapshot = _jarvisContext.value,
            )
            _messages.value = _messages.value + assistantMessage
            _isProcessing.value = false

            // Persist chat history
            memoryStorage.saveChatHistory(_messages.value)
        }
    }

    /**
     * Load the Gemma model from disk.
     */
    fun loadModel(path: String) {
        viewModelScope.launch {
            gemmaEngine.loadModel(path)
            memoryStorage.setModelPath(path)
        }
    }

    /**
     * Start a vehicle classification burst.
     */
    fun classifyVehicle() {
        viewModelScope.launch {
            val result = motionClassifier.runClassificationBurst()
            vehicleSessionManager.onClassificationResult(result)

            // Update context
            _jarvisContext.value = _jarvisContext.value.copy(
                vehicleSession = vehicleSessionManager.currentSession.value,
            )
        }
    }

    /**
     * Start location tracking.
     */
    fun startLocationTracking() {
        contextManager.startLocationTracking()
        viewModelScope.launch {
            contextManager.currentLocation.collect { location ->
                _jarvisContext.value = _jarvisContext.value.copy(
                    location = location,
                    placeContext = contextManager.currentPlace.value,
                )
            }
        }
    }

    /**
     * Stop location tracking.
     */
    fun stopLocationTracking() {
        contextManager.stopLocationTracking()
    }

    /**
     * Clear chat history.
     */
    fun clearChat() {
        _messages.value = emptyList()
        viewModelScope.launch {
            memoryStorage.saveChatHistory(emptyList())
        }
    }

    /**
     * Build a text summary of current context for the LLM prompt.
     */
    private fun buildContextSummary(): String {
        val ctx = _jarvisContext.value
        val parts = mutableListOf<String>()

        ctx.location?.let { loc ->
            parts.add("Location: ${loc.latitude}, ${loc.longitude} (accuracy: ${loc.accuracy}m, speed: ${"%.1f".format(loc.speed * 3.6)} km/h)")
        }

        ctx.placeContext?.let { place ->
            parts.add("Place: ${place.label} (${place.placeType}, confidence: ${place.confidence})")
        }

        ctx.vehicleSession?.let { session ->
            parts.add("Vehicle: ${session.vehicleIdentity} (state: ${session.state}, confidence: ${session.confidence})")
        }

        parts.add("Motion: ${ctx.motion}")

        ctx.battery?.let { bat ->
            parts.add("Battery: ${bat.level}%, charging: ${bat.isCharging}")
        }

        return if (parts.isEmpty()) "No sensor context available." else parts.joinToString("\n")
    }

    /**
     * Fallback response when model is not loaded.
     */
    private fun buildOfflineResponse(userMessage: String): String {
        val lower = userMessage.lowercase()
        return when {
            "remind" in lower || "reminder" in lower ->
                "I understand you want to set a reminder. To enable smart context-aware reminders, please load the Gemma model in Settings. I'll then be able to parse your intent and set geofence/vehicle triggers."

            "where" in lower || "location" in lower -> {
                val loc = _jarvisContext.value.location
                if (loc != null) {
                    "Your current location is (${loc.latitude}, ${loc.longitude}) with ${loc.accuracy}m accuracy."
                } else {
                    "Location is not available. Please enable location tracking in the Dashboard."
                }
            }

            "vehicle" in lower || "bike" in lower || "hunter" in lower -> {
                val session = _jarvisContext.value.vehicleSession
                if (session != null) {
                    "Vehicle session: ${session.vehicleIdentity} (${session.state}, confidence: ${"%.0f".format(session.confidence * 100)}%)"
                } else {
                    "No active vehicle session. Start a classification burst from the Dashboard when you're on your vehicle."
                }
            }

            "hello" in lower || "hi" in lower ->
                "Hello! I'm Jarvis, your on-device AI assistant. I can help with context-aware reminders, vehicle tracking, and more. Load the Gemma model in Settings for full capabilities."

            else ->
                "I'm running in offline mode. Load the Gemma model in Settings for full AI capabilities. I can still show your sensor context and run vehicle classification."
        }
    }

    override fun onCleared() {
        super.onCleared()
        contextManager.stopLocationTracking()
        motionClassifier.stopClassification()
        gemmaEngine.unload()
    }
}
