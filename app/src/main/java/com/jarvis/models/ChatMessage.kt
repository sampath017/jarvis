package com.jarvis.models

/**
 * Chat message for the Jarvis conversation UI.
 */
data class ChatMessage(
    val id: String,
    val content: String,
    val role: MessageRole,
    val timestamp: Long = System.currentTimeMillis(),
    val contextSnapshot: JarvisContext? = null,
    val isStreaming: Boolean = false,
)

enum class MessageRole {
    USER,
    ASSISTANT,
    SYSTEM,
}
