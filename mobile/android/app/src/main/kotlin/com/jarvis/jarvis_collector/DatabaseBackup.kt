package com.jarvis.jarvis_collector

import android.accounts.Account
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.work.*
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import com.google.android.gms.tasks.Tasks
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** One private Drive file, with a consistent WAL-aware snapshot and verified replacement. */
object DatabaseBackup {
    private const val WEEKLY = "jarvis_database_backup_weekly"
    private const val NOW = "jarvis_database_backup_now"
    private val running = AtomicBoolean(false)
    private fun prefs(c: Context) = c.getSharedPreferences("jarvis_database_backup", Context.MODE_PRIVATE)
    private fun google(c: Context) = c.getSharedPreferences("jarvis_google_drive", Context.MODE_PRIVATE)
    private fun connected(c: Context) = google(c).getBoolean("connected", false)
    fun status(c: Context): Map<String, Any?> = mapOf(
        "enabled" to prefs(c).getBoolean("enabled", true), "connected" to connected(c),
        "lastSuccess" to prefs(c).getLong("last_success:${google(c).getString("email", "")}", 0), "state" to prefs(c).getString("state", "scheduled"),
        "error" to prefs(c).getString("error", null))
    fun configure(c: Context, value: Boolean) {
        check(prefs(c).edit().putBoolean("enabled", value).commit())
        if (value) schedule(c) else cancel(c)
    }
    fun cancel(c: Context) {
        WorkManager.getInstance(c).cancelUniqueWork(WEEKLY)
        WorkManager.getInstance(c).cancelUniqueWork(NOW)
    }
    private fun constraints() = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED)
        .setRequiresBatteryNotLow(true).build()
    fun schedule(c: Context) {
        if (!JarvisPower.enabled(c) || !prefs(c).getBoolean("enabled", true) || !connected(c)) return
        val now = ZonedDateTime.now(ZoneId.of("Asia/Kolkata"))
        val work = PeriodicWorkRequestBuilder<DatabaseBackupWorker>(7, TimeUnit.DAYS)
            .setInitialDelay(DatabaseBackupPolicy.delay(now), TimeUnit.MILLISECONDS)
            .setConstraints(constraints()).build()
        WorkManager.getInstance(c).enqueueUniquePeriodicWork(WEEKLY, ExistingPeriodicWorkPolicy.KEEP, work)
        val account = google(c).getString("email", "")
        if (prefs(c).getLong("last_success:$account", 0) == 0L ||
            prefs(c).getString("file_name:$account", null) != DatabaseBackupPolicy.FILE_NAME) enqueue(c)
    }
    fun enqueue(c: Context) {
        check(JarvisPower.enabled(c) && prefs(c).getBoolean("enabled", true)) { "Turn on Jarvis and weekly backup first." }
        check(connected(c)) { "Connect Google Drive in Settings first." }
        prefs(c).edit().putString("state", "queued").remove("error").commit()
        WorkManager.getInstance(c).enqueueUniqueWork(NOW, ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<DatabaseBackupWorker>().setConstraints(constraints()).build())
    }
    fun perform(c: Context, stopped: () -> Boolean): Boolean {
        if (!running.compareAndSet(false, true)) return false
        var snapshot: File? = null
        try {
            val email = google(c).getString("email", "") ?: ""
            fun checkActive() {
                check(!stopped() && JarvisPower.enabled(c) && prefs(c).getBoolean("enabled", true)) { "Backup paused." }
                check(connected(c) && email.isNotBlank() && google(c).getString("email", "") == email) { "Reconnect Google Drive." }
            }
            checkActive()
            prefs(c).edit().putString("state", "running").remove("error").commit()
            val scopes = listOf(Scope("https://www.googleapis.com/auth/drive.file"), Scope("https://www.googleapis.com/auth/drive.readonly"))
            val authorization = Tasks.await(Identity.getAuthorizationClient(c).authorize(
                AuthorizationRequest.builder().setAccount(Account(email, "com.google")).setRequestedScopes(scopes).build()), 30, TimeUnit.SECONDS)
            check(!authorization.hasResolution() && !authorization.accessToken.isNullOrBlank()) { "Reconnect Google Drive to allow backup." }
            val token = authorization.accessToken!!
            fun request(method: String, path: String, body: ByteArray? = null, mime: String = "application/json", file: File? = null): Pair<JSONObject, String?> {
                checkActive()
                val url = if (path.startsWith("https://")) URL(path) else URL("https://www.googleapis.com$path")
                check(url.protocol == "https" && url.host == "www.googleapis.com" && url.path.startsWith("/"))
                val connection = url.openConnection() as HttpURLConnection
                JarvisPower.track(c, connection)
                try {
                    connection.requestMethod = method
                    connection.instanceFollowRedirects = false
                    connection.connectTimeout = 20_000; connection.readTimeout = 60_000
                    connection.setRequestProperty("Authorization", "Bearer $token")
                    if (body != null || file != null) {
                        connection.doOutput = true
                        connection.setRequestProperty("Content-Type", mime)
                        connection.setFixedLengthStreamingMode(file?.length() ?: body!!.size.toLong())
                        connection.outputStream.use { output ->
                            if (file == null) output.write(body!!) else file.inputStream().use { input ->
                                val buffer = ByteArray(64 * 1024)
                                while (true) {
                                    checkActive()
                                    val size = input.read(buffer)
                                    if (size < 0) break
                                    output.write(buffer, 0, size)
                                }
                            }
                        }
                    }
                    val code = connection.responseCode
                    check(code in 200..299) { if (code == 401 || code == 403) "Reconnect Google Drive to allow backup." else "Drive backup request failed ($code)." }
                    val text = connection.inputStream.bufferedReader().use { it.readText() }
                    return (if (text.isBlank()) JSONObject() else JSONObject(text)) to connection.getHeaderField("Location")
                } finally { JarvisPower.release(connection) }
            }
            fun json(method: String, path: String, body: JSONObject? = null) = request(method, path, body?.toString()?.toByteArray()) .first
            fun query(q: String, fields: String) = json("GET", "/drive/v3/files?q=${URLEncoder.encode(q, "UTF-8")}&fields=${URLEncoder.encode(fields, "UTF-8")}&pageSize=1000").getJSONArray("files")
            fun objects(rows: JSONArray) = (0 until rows.length()).map { rows.getJSONObject(it) }
            fun privateOwned(file: JSONObject) = file.optBoolean("ownedByMe") && !file.optBoolean("shared", true) && !file.optBoolean("trashed", true)
            val fields = "id,name,mimeType,ownedByMe,shared,trashed,parents,appProperties"
            val folders = objects(query("trashed=false and 'root' in parents and 'me' in owners and name='Jarvis' and mimeType='application/vnd.google-apps.folder'", "files($fields)"))
            check(folders.size <= 1 && folders.all(::privateOwned)) { "Use one private Jarvis folder owned by you in Drive." }
            val folder = folders.firstOrNull() ?: json("POST", "/drive/v3/files?fields=${URLEncoder.encode(fields,"UTF-8")}",
                JSONObject().put("name", "Jarvis").put("mimeType", "application/vnd.google-apps.folder").put("parents", JSONArray().put("root"))
                    .put("appProperties", JSONObject().put("jarvisFolder", "Jarvis")))
            check(privateOwned(folder)) { "The Jarvis folder must be private and owned by you." }
            val folderId = folder.getString("id")
            val files = objects(query("trashed=false and '$folderId' in parents and (name='${DatabaseBackupPolicy.FILE_NAME}' or name='${DatabaseBackupPolicy.LEGACY_FILE_NAME}')", "files($fields)"))
            check(files.size <= 1) { "Multiple jarvis_db_backup.db files exist. Keep the intended backup in Jarvis and retry." }
            val existing = files.firstOrNull()
            check(existing == null || (privateOwned(existing) && existing.optJSONObject("appProperties")?.optString("jarvisBackup") == "database")) {
                "A different file already uses jarvis_db_backup.db. Rename it in Drive before backing up."
            }
            if (existing != null && existing.optString("name") != DatabaseBackupPolicy.FILE_NAME) {
                json("PATCH", "/drive/v3/files/${existing.getString("id")}", JSONObject().put("name", DatabaseBackupPolicy.FILE_NAME))
            }
            val database = c.getDatabasePath("jarvis_mobile.db")
            check(database.isFile) { "Open Jarvis once before backing up its database." }
            val copy = File.createTempFile("jarvis-db-", ".sqlite", c.cacheDir).also { check(it.delete()) }
            snapshot = copy
            SQLiteDatabase.openDatabase(database.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
                db.execSQL("VACUUM INTO ?", arrayOf(copy.path))
            }
            SQLiteDatabase.openDatabase(copy.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("PRAGMA integrity_check", null).use { cursor -> check(cursor.moveToFirst() && cursor.getString(0) == "ok") { "Database backup integrity check failed." } }
            }
            val md5 = MessageDigest.getInstance("MD5")
            copy.inputStream().use { input -> val buffer = ByteArray(65536); while (true) { val n = input.read(buffer); if (n < 0) break; md5.update(buffer, 0, n) } }
            val digest = md5.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
            val key = "file:$email"
            val fileId = existing?.getString("id") ?: prefs(c).getString("pending:$email", null) ?: run {
                val id = json("GET", "/drive/v3/files/generateIds?count=1&space=drive&type=files").getJSONArray("ids").getString(0)
                check(prefs(c).edit().putString("pending:$email", id).commit()); id
            }
            if (existing != null) {
                request("PATCH", "/upload/drive/v3/files/$fileId?uploadType=media", mime="application/vnd.sqlite3", file=copy)
            } else {
                val metadata = JSONObject().put("id", fileId).put("name", DatabaseBackupPolicy.FILE_NAME).put("parents", JSONArray().put(folderId))
                    .put("mimeType", "application/vnd.sqlite3").put("appProperties", JSONObject().put("jarvisBackup", "database"))
                val upload = request("POST", "/upload/drive/v3/files?uploadType=resumable", metadata.toString().toByteArray()).second
                check(!upload.isNullOrBlank()) { "Drive did not return an upload session." }
                request("PUT", upload, mime="application/vnd.sqlite3", file=copy)
            }
            val verified = json("GET", "/drive/v3/files/$fileId?fields=id,name,size,md5Checksum,headRevisionId")
            check(verified.optString("name") == DatabaseBackupPolicy.FILE_NAME && verified.optString("md5Checksum") == digest && verified.optString("size").toLongOrNull() == copy.length()) { "Drive backup verification failed; retry required." }
            // Only prune this managed backup's history after the new snapshot is verified.
            val head = verified.getString("headRevisionId")
            var page = ""
            val revisions = mutableListOf<String>()
            do {
                val rows = json("GET", "/drive/v3/files/$fileId/revisions?fields=revisions(id),nextPageToken&pageSize=1000" +
                    if (page.isEmpty()) "" else "&pageToken=${URLEncoder.encode(page,"UTF-8")}")
                revisions.addAll(objects(rows.optJSONArray("revisions") ?: JSONArray()).map { it.getString("id") })
                page = rows.optString("nextPageToken")
            } while (page.isNotEmpty())
            DatabaseBackupPolicy.oldRevisions(revisions, head).forEach { revision ->
                // Binary revisions must be pinned before Drive permits explicit deletion.
                json("PATCH", "/drive/v3/files/$fileId/revisions/$revision", JSONObject().put("keepForever", true))
                json("DELETE", "/drive/v3/files/$fileId/revisions/$revision")
            }
            checkActive()
            check(prefs(c).edit().putString(key, fileId).putLong("last_success:$email", System.currentTimeMillis())
                .putString("file_name:$email", DatabaseBackupPolicy.FILE_NAME).putString("state", "complete").remove("pending:$email").remove("error").commit())
            return true
        } catch (error: Exception) {
            prefs(c).edit().putString("state", "failed").putString("error", error.message?.take(180) ?: "Backup failed. Please retry.").commit()
            return false
        } finally {
            snapshot?.let { file ->
                file.delete()
                File(file.path + "-wal").delete()
                File(file.path + "-shm").delete()
            }
            running.set(false)
        }
    }
}

class DatabaseBackupWorker(c: Context, parameters: WorkerParameters) : Worker(c, parameters) {
    override fun doWork(): Result {
        if (!JarvisPower.enabled(applicationContext)) return Result.success()
        return if (DatabaseBackup.perform(applicationContext) { isStopped }) Result.success() else Result.retry()
    }
}
