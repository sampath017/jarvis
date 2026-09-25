package com.jarvis.jarvis_collector

import android.app.Activity
import android.content.Intent
import android.provider.OpenableColumns
import android.net.Uri
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.util.UUID

/** The system picker grants access only to the PDF/image/video the user selects. */
class ChatAttachmentPicker(private val activity: MainActivity, messenger: BinaryMessenger) {
    private var pending: MethodChannel.Result? = null
    private val directory = File(activity.cacheDir, "jarvis_attachments").apply { mkdirs() }
    init {
        MethodChannel(messenger, "com.jarvis/attachments").setMethodCallHandler { call, result ->
            when (call.method) {
                "open" -> {
                    val uri = Uri.parse(call.arguments.toString())
                    if (uri.scheme != "https" || uri.host != "drive.google.com") result.error("URL", "Invalid Google Drive link.", null)
                    else try { activity.startActivity(Intent(Intent.ACTION_VIEW, uri)); result.success(true) }
                        catch (_: Exception) { result.error("OPEN", "Could not open Google Drive.", null) }
                }
                "pick" -> {
                    if (pending != null) result.error("BUSY", "File picker already open.", null)
                    else {
                        pending = result
                        try { activity.startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT)
                            .addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
                            .putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/pdf", "image/*", "video/*")), 8730) }
                        catch (_: Exception) { pending = null; result.error("PICKER", "Could not open file picker.", null) }
                    }
                }
                "removeCached" -> {
                    val file = File(call.arguments.toString()).canonicalFile
                    if (file.parentFile == directory.canonicalFile) { file.delete(); result.success(true) }
                    else result.error("PATH", "Invalid attachment cache path.", null)
                }
                else -> result.notImplemented()
            }
        }
    }
    fun onActivityResult(requestCode: Int, resultCode: Int, intent: Intent?) {
        if (requestCode != 8730) return
        val result = pending ?: return
        pending = null
        val uri = intent?.data
        if (resultCode != Activity.RESULT_OK || uri == null) { result.success(null); return }
        Thread {
            var copied: File? = null
            try {
                val resolver = activity.contentResolver
                val mime = resolver.getType(uri) ?: "application/octet-stream"
                if (mime != "application/pdf" && !mime.startsWith("image/") && !mime.startsWith("video/")) throw IllegalArgumentException("Select a PDF, image or video.")
                var name = "attachment"
                resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
                    if (cursor.moveToFirst()) {
                        name = cursor.getString(0) ?: name
                        if (!cursor.isNull(1) && cursor.getLong(1) > 250L * 1024 * 1024) throw IllegalArgumentException("Choose a file up to 250 MB.")
                    }
                }
                val id = UUID.randomUUID().toString()
                val target = File(directory, id)
                copied = target
                var size = 0L
                resolver.openInputStream(uri)!!.use { input -> target.outputStream().use { output ->
                    val buffer = ByteArray(65536)
                    while (true) {
                        val read = input.read(buffer); if (read < 0) break
                        size += read
                        if (size > 250L * 1024 * 1024) throw IllegalArgumentException("Choose a file up to 250 MB.")
                        output.write(buffer, 0, read)
                    }
                } }
                if (size == 0L) throw IllegalArgumentException("This file is empty.")
                val data = mapOf("id" to id, "name" to name.take(255), "mimeType" to mime, "size" to size, "path" to target.absolutePath)
                activity.runOnUiThread { result.success(data) }
            } catch (e: Exception) {
                copied?.delete()
                activity.runOnUiThread { result.error("ATTACHMENT", e.message ?: "Could not read this file.", null) }
            }
        }.start()
    }
}
