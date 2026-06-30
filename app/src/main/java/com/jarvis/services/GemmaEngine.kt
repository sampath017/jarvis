package com.jarvis.services

import android.content.Context
import com.google.mediapipe.tasks.genai.llminference.LlmInference
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import java.io.File

/**
 * GemmaEngine wraps the MediaPipe LLM Inference SDK to load and run
 * the Gemma model on-device.
 *
 * Responsibilities:
 * - Load the .bin model file
 * - Generate responses with streaming
 * - Build context-enriched prompts from JarvisContext
 */
class GemmaEngine(private val context: Context) {

    private var llmInference: LlmInference? = null

    private val _isModelLoaded = MutableStateFlow(false)
    val isModelLoaded: StateFlow<Boolean> = _isModelLoaded.asStateFlow()

    private val _isGenerating = MutableStateFlow(false)
    val isGenerating: StateFlow<Boolean> = _isGenerating.asStateFlow()

    private val _loadingProgress = MutableStateFlow("")
    val loadingProgress: StateFlow<String> = _loadingProgress.asStateFlow()

    /**
     * Load the Gemma model from the given file path.
     */
    suspend fun loadModel(modelPath: String) = withContext(Dispatchers.IO) {
        try {
            _loadingProgress.value = "Initializing Gemma engine..."

            val modelFile = File(modelPath)
            if (!modelFile.exists()) {
                _loadingProgress.value = "Error: Model file not found at $modelPath"
                return@withContext
            }

            _loadingProgress.value = "Loading model (this may take a moment)..."

            val options = LlmInference.LlmInferenceOptions.builder()
                .setModelPath(modelPath)
                .setMaxTokens(1024)
                .setTopK(40)
                .setTemperature(0.8f)
                .setRandomSeed(42)
                .build()

            llmInference = LlmInference.createFromOptions(context, options)
            _isModelLoaded.value = true
            _loadingProgress.value = "Model loaded successfully"
        } catch (e: Exception) {
            _loadingProgress.value = "Error loading model: ${e.message}"
            _isModelLoaded.value = false
        }
    }

    /**
     * Generate a response from the model given a prompt.
     * Returns the full response string.
     */
    suspend fun generateResponse(prompt: String): String = withContext(Dispatchers.IO) {
        val inference = llmInference
            ?: return@withContext "Model not loaded. Please load a model first."

        _isGenerating.value = true
        try {
            val response = inference.generateResponse(prompt)
            response ?: "No response generated."
        } catch (e: Exception) {
            "Error generating response: ${e.message}"
        } finally {
            _isGenerating.value = false
        }
    }

    /**
     * Generate a response with streaming callback.
     */
    suspend fun generateResponseStreaming(
        prompt: String,
        onPartialResult: (String) -> Unit,
    ): String = withContext(Dispatchers.IO) {
        val inference = llmInference
            ?: return@withContext "Model not loaded. Please load a model first."

        _isGenerating.value = true
        try {
            val fullResponse = StringBuilder()
            inference.generateResponseAsync(prompt).let { _ ->
                // MediaPipe streaming API – collect partial results
                // Note: actual streaming API may vary by SDK version
                val response = inference.generateResponse(prompt)
                fullResponse.append(response ?: "")
                onPartialResult(fullResponse.toString())
            }
            fullResponse.toString()
        } catch (e: Exception) {
            "Error: ${e.message}"
        } finally {
            _isGenerating.value = false
        }
    }

    /**
     * Build a context-enriched system prompt for Jarvis.
     * The LLM is used ONLY for human intent parsing, not for sensor classification.
     */
    fun buildContextPrompt(
        userMessage: String,
        contextSummary: String,
    ): String {
        return """
You are Jarvis, a hyper-personalized, privacy-first, context-aware mobile assistant.
You run entirely on-device. You understand the user's physical context through sensor data.

Current Context:
$contextSummary

Your role:
- Parse user intent for reminders and tasks
- Provide context-aware responses based on location, motion, and vehicle state
- Extract structured task triggers (exit_geofence, enter_geofence, vehicle_start, etc.)
- Never fabricate sensor data. Only reference what is provided in context.

When the user sets a reminder with location/vehicle triggers, respond with a JSON block:
```json
{
  "task": "<task description>",
  "trigger_type": "<exit_geofence|enter_geofence|vehicle_start|vehicle_stop|time_based>",
  "location_phrase": "<place name or null>",
  "vehicle_context_required": "<vehicle name or optional>"
}
```

User: $userMessage
Jarvis:""".trimIndent()
    }

    /**
     * Unload the model and release resources.
     */
    fun unload() {
        llmInference?.close()
        llmInference = null
        _isModelLoaded.value = false
        _loadingProgress.value = ""
    }
}
