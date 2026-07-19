package com.jarvis.edge.data.repository

import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.ListenerRegistration
import com.google.firebase.firestore.Query
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.tasks.await
import java.util.ArrayList
import java.util.UUID

class FirestoreRepository {

    private val db = FirebaseFirestore.getInstance()

    fun getTasks(uid: String): Flow<List<Map<String, Any>>> = callbackFlow {
        val query = db.collection("users").document(uid).collection("tasks")
        val listener = query.addSnapshotListener { snapshot, error ->
            if (error != null) {
                android.util.Log.e("FirestoreRepository", "Error fetching tasks: ${error.message}", error)
                return@addSnapshotListener
            }
            val list = ArrayList<Map<String, Any>>()
            snapshot?.forEach { doc ->
                val data = doc.data.toMutableMap()
                data["id"] = doc.id
                list.add(data)
            }
            trySend(list)
        }
        awaitClose { listener.remove() }
    }


    fun getNotes(uid: String): Flow<List<Map<String, Any>>> = callbackFlow {
        val query = db.collection("users").document(uid).collection("notes")
        val listener = query.addSnapshotListener { snapshot, error ->
            if (error != null) {
                android.util.Log.e("FirestoreRepository", "Error fetching notes: ${error.message}", error)
                return@addSnapshotListener
            }
            val list = ArrayList<Map<String, Any>>()
            snapshot?.forEach { doc ->
                val data = doc.data.toMutableMap()
                data["id"] = doc.id
                list.add(data)
            }
            trySend(list)
        }
        awaitClose { listener.remove() }
    }

    fun getActiveSession(uid: String): Flow<Map<String, Any>?> = callbackFlow {
        // Query status values that mean session is not completed/expired
        val query = db.collection("users").document(uid).collection("mobilitySessions")
            .whereIn("status", listOf("ACTIVE", "PAUSED", "RESUMED"))
            .limit(1)

        val listener = query.addSnapshotListener { snapshot, error ->
            if (error != null) {
                android.util.Log.e("FirestoreRepository", "Error fetching active session: ${error.message}", error)
                return@addSnapshotListener
            }
            val doc = snapshot?.documents?.firstOrNull()
            if (doc != null) {
                val data = doc.data?.toMutableMap() ?: HashMap()
                data["id"] = doc.id
                trySend(data)
            } else {
                trySend(null)
            }
        }
        awaitClose { listener.remove() }
    }

    suspend fun completeSession(uid: String, sessionId: String): Result<Unit> = runCatching {
        db.collection("users").document(uid).collection("mobilitySessions").document(sessionId)
            .update(
                mapOf(
                    "status" to "COMPLETED",
                    "completed_at" to FieldValue.serverTimestamp(),
                    "last_updated" to FieldValue.serverTimestamp()
                )
            )
            .await()
    }

    fun getChatThreads(uid: String): Flow<List<Map<String, Any>>> = callbackFlow {
        val query = db.collection("users").document(uid).collection("chatThreads")
            .orderBy("updated_at", Query.Direction.DESCENDING)
            .limit(50)
        val listener = query.addSnapshotListener { snapshot, error ->
            if (error != null) {
                android.util.Log.e("FirestoreRepository", "Error fetching chat threads", error)
                return@addSnapshotListener
            }
            val threads = snapshot?.documents.orEmpty().map { document ->
                (document.data ?: emptyMap()).toMutableMap().apply { put("id", document.id) }
            }
            trySend(threads)
        }
        awaitClose { listener.remove() }
    }

    fun getChatMessages(uid: String, threadId: String): Flow<List<Map<String, Any>>> = callbackFlow {
        val query = db.collection("users").document(uid).collection("chatThreads")
            .document(threadId)
            .collection("messages")
            .orderBy("timestamp", Query.Direction.ASCENDING)
            .limit(200)
        val listener = query.addSnapshotListener { snapshot, error ->
            if (error != null) {
                android.util.Log.e("FirestoreRepository", "Error fetching chat messages", error)
                return@addSnapshotListener
            }
            val messages = snapshot?.documents.orEmpty().map { document ->
                (document.data ?: emptyMap()).toMutableMap().apply { put("id", document.id) }
            }
            trySend(messages)
        }
        awaitClose { listener.remove() }
    }

    suspend fun createChatThread(uid: String, title: String = "New chat"): Result<Map<String, Any>> = runCatching {
        val threadId = UUID.randomUUID().toString()
        val data = mapOf(
            "thread_id" to threadId,
            "title" to title,
            "created_at" to FieldValue.serverTimestamp(),
            "updated_at" to FieldValue.serverTimestamp()
        )
        db.collection("users").document(uid).collection("chatThreads").document(threadId)
            .set(data)
            .await()
        mapOf("id" to threadId, "title" to title)
    }

    suspend fun renameChatThread(uid: String, threadId: String, title: String): Result<Unit> = runCatching {
        db.collection("users").document(uid).collection("chatThreads").document(threadId)
            .update(
                mapOf(
                    "title" to title.trim(),
                    "updated_at" to FieldValue.serverTimestamp()
                )
            )
            .await()
    }

    suspend fun deleteChatThread(uid: String, threadId: String): Result<Unit> = runCatching {
        val thread = db.collection("users").document(uid).collection("chatThreads").document(threadId)
        while (true) {
            val messages = thread.collection("messages").limit(400).get().await()
            if (messages.isEmpty) break
            val batch = db.batch()
            messages.documents.forEach { message -> batch.delete(message.reference) }
            batch.commit().await()
        }
        thread.delete().await()
    }

    suspend fun deleteAllChatThreads(uid: String): Result<Unit> = runCatching {
        val threads = db.collection("users").document(uid).collection("chatThreads").get().await()
        threads.documents.forEach { thread ->
            deleteChatThread(uid, thread.id).getOrThrow()
        }
    }

    suspend fun editChatMessage(
        uid: String,
        threadId: String,
        messageId: String,
        content: String
    ): Result<Unit> = runCatching {
        db.collection("users").document(uid).collection("chatThreads").document(threadId)
            .collection("messages").document(messageId)
            .update(
                mapOf(
                    "content" to content.trim(),
                    "edited_at" to FieldValue.serverTimestamp()
                )
            )
            .await()
    }

    suspend fun deleteChatMessage(uid: String, threadId: String, messageId: String): Result<Unit> = runCatching {
        db.collection("users").document(uid).collection("chatThreads").document(threadId)
            .collection("messages").document(messageId)
            .delete()
            .await()
    }

    // ── Planner CRUD ────────────────────────────────────────────────────

    suspend fun createTask(
        uid: String,
        title: String,
        dueDate: String? = null,
        triggerPlace: String? = null
    ): Result<String> = runCatching {
        val id = UUID.randomUUID().toString()
        val data = mutableMapOf<String, Any>(
            "title" to title.trim(),
            "created_at" to FieldValue.serverTimestamp()
        )
        dueDate?.trim()?.takeIf { it.isNotEmpty() }?.let { data["due_date"] = it }
        triggerPlace?.trim()?.takeIf { it.isNotEmpty() }?.let { data["trigger_place"] = it }

        db.collection("users").document(uid).collection("tasks").document(id)
            .set(data).await()
        id
    }

    suspend fun updateTask(
        uid: String,
        taskId: String,
        title: String,
        dueDate: String? = null,
        triggerPlace: String? = null
    ): Result<Unit> = runCatching {
        val data = mutableMapOf<String, Any>(
            "title" to title.trim(),
            "updated_at" to FieldValue.serverTimestamp()
        )
        if (dueDate != null) {
            data["due_date"] = if (dueDate.isBlank()) FieldValue.delete() else dueDate.trim()
        }
        if (triggerPlace != null) {
            data["trigger_place"] = if (triggerPlace.isBlank()) FieldValue.delete() else triggerPlace.trim()
        }

        db.collection("users").document(uid).collection("tasks").document(taskId)
            .update(data)
            .await()
    }

    suspend fun deleteTask(uid: String, taskId: String): Result<Unit> = runCatching {
        db.collection("users").document(uid).collection("tasks").document(taskId)
            .delete().await()
    }

    suspend fun createNote(uid: String, content: String): Result<String> = runCatching {
        val id = UUID.randomUUID().toString()
        val data = mapOf(
            "content" to content.trim(),
            "created_at" to FieldValue.serverTimestamp()
        )
        db.collection("users").document(uid).collection("notes").document(id)
            .set(data).await()
        id
    }

    suspend fun updateNote(uid: String, noteId: String, content: String): Result<Unit> = runCatching {
        db.collection("users").document(uid).collection("notes").document(noteId)
            .update(mapOf("content" to content.trim(), "updated_at" to FieldValue.serverTimestamp()))
            .await()
    }

    suspend fun deleteNote(uid: String, noteId: String): Result<Unit> = runCatching {
        db.collection("users").document(uid).collection("notes").document(noteId)
            .delete().await()
    }
}
