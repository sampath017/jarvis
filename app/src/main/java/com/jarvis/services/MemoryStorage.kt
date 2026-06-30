package com.jarvis.services

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import com.jarvis.models.*
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import org.json.JSONArray
import org.json.JSONObject

// Extension for DataStore
private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "jarvis_memory")

/**
 * MemoryStorage handles persistent storage using DataStore.
 * Stores:
 * - Known places (personal place memory)
 * - Tasks/reminders
 * - Vehicle profiles
 * - Chat history
 * - User preferences/settings
 */
class MemoryStorage(private val context: Context) {

    // Preference keys
    private object Keys {
        val KNOWN_PLACES = stringPreferencesKey("known_places")
        val TASKS = stringPreferencesKey("tasks")
        val VEHICLE_PROFILES = stringPreferencesKey("vehicle_profiles")
        val CHAT_HISTORY = stringPreferencesKey("chat_history")
        val MODEL_PATH = stringPreferencesKey("model_path")
        val USER_NAME = stringPreferencesKey("user_name")
        val IS_ONBOARDED = booleanPreferencesKey("is_onboarded")
    }

    // --- Known Places ---

    suspend fun saveKnownPlaces(places: List<KnownPlace>) {
        val json = JSONArray().apply {
            places.forEach { place ->
                put(JSONObject().apply {
                    put("id", place.id)
                    put("label", place.label)
                    put("latitude", place.latitude)
                    put("longitude", place.longitude)
                    put("radiusM", place.radiusM.toDouble())
                    put("type", place.type.name)
                })
            }
        }
        context.dataStore.edit { prefs ->
            prefs[Keys.KNOWN_PLACES] = json.toString()
        }
    }

    fun getKnownPlacesFlow(): Flow<List<KnownPlace>> {
        return context.dataStore.data.map { prefs ->
            val json = prefs[Keys.KNOWN_PLACES] ?: return@map emptyList()
            parseKnownPlaces(json)
        }
    }

    suspend fun getKnownPlaces(): List<KnownPlace> = getKnownPlacesFlow().first()

    private fun parseKnownPlaces(json: String): List<KnownPlace> {
        return try {
            val array = JSONArray(json)
            (0 until array.length()).map { i ->
                val obj = array.getJSONObject(i)
                KnownPlace(
                    id = obj.getString("id"),
                    label = obj.getString("label"),
                    latitude = obj.getDouble("latitude"),
                    longitude = obj.getDouble("longitude"),
                    radiusM = obj.getDouble("radiusM").toFloat(),
                    type = PlaceType.valueOf(obj.optString("type", "CUSTOM")),
                )
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    // --- Tasks / Reminders ---

    suspend fun saveTasks(tasks: List<JarvisTask>) {
        val json = JSONArray().apply {
            tasks.forEach { task ->
                put(JSONObject().apply {
                    put("id", task.id)
                    put("task", task.task)
                    put("triggerType", task.triggerType.name)
                    put("locationPhrase", task.locationPhrase ?: "")
                    put("vehicleContextRequired", task.vehicleContextRequired ?: "")
                    put("isActive", task.isActive)
                    put("createdAt", task.createdAt)
                })
            }
        }
        context.dataStore.edit { prefs ->
            prefs[Keys.TASKS] = json.toString()
        }
    }

    fun getTasksFlow(): Flow<List<JarvisTask>> {
        return context.dataStore.data.map { prefs ->
            val json = prefs[Keys.TASKS] ?: return@map emptyList()
            parseTasks(json)
        }
    }

    private fun parseTasks(json: String): List<JarvisTask> {
        return try {
            val array = JSONArray(json)
            (0 until array.length()).map { i ->
                val obj = array.getJSONObject(i)
                JarvisTask(
                    id = obj.getString("id"),
                    task = obj.getString("task"),
                    triggerType = TaskTriggerType.valueOf(obj.getString("triggerType")),
                    locationPhrase = obj.optString("locationPhrase").ifEmpty { null },
                    vehicleContextRequired = obj.optString("vehicleContextRequired").ifEmpty { null },
                    isActive = obj.optBoolean("isActive", true),
                    createdAt = obj.optLong("createdAt", System.currentTimeMillis()),
                )
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    // --- Chat History ---

    suspend fun saveChatHistory(messages: List<ChatMessage>) {
        // Keep only last 100 messages
        val trimmed = messages.takeLast(100)
        val json = JSONArray().apply {
            trimmed.forEach { msg ->
                put(JSONObject().apply {
                    put("id", msg.id)
                    put("content", msg.content)
                    put("role", msg.role.name)
                    put("timestamp", msg.timestamp)
                })
            }
        }
        context.dataStore.edit { prefs ->
            prefs[Keys.CHAT_HISTORY] = json.toString()
        }
    }

    fun getChatHistoryFlow(): Flow<List<ChatMessage>> {
        return context.dataStore.data.map { prefs ->
            val json = prefs[Keys.CHAT_HISTORY] ?: return@map emptyList()
            parseChatHistory(json)
        }
    }

    private fun parseChatHistory(json: String): List<ChatMessage> {
        return try {
            val array = JSONArray(json)
            (0 until array.length()).map { i ->
                val obj = array.getJSONObject(i)
                ChatMessage(
                    id = obj.getString("id"),
                    content = obj.getString("content"),
                    role = MessageRole.valueOf(obj.getString("role")),
                    timestamp = obj.optLong("timestamp", System.currentTimeMillis()),
                )
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    // --- Settings ---

    suspend fun setModelPath(path: String) {
        context.dataStore.edit { prefs -> prefs[Keys.MODEL_PATH] = path }
    }

    fun getModelPathFlow(): Flow<String?> {
        return context.dataStore.data.map { prefs -> prefs[Keys.MODEL_PATH] }
    }

    suspend fun setUserName(name: String) {
        context.dataStore.edit { prefs -> prefs[Keys.USER_NAME] = name }
    }

    fun getUserNameFlow(): Flow<String> {
        return context.dataStore.data.map { prefs -> prefs[Keys.USER_NAME] ?: "User" }
    }

    suspend fun setOnboarded(value: Boolean) {
        context.dataStore.edit { prefs -> prefs[Keys.IS_ONBOARDED] = value }
    }

    fun getOnboardedFlow(): Flow<Boolean> {
        return context.dataStore.data.map { prefs -> prefs[Keys.IS_ONBOARDED] ?: false }
    }
}
