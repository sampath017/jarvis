package com.jarvis.jarvis_collector

import android.app.Activity
import android.app.Instrumentation
import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import android.os.Bundle
import org.json.JSONObject
import java.io.File
import java.util.UUID

/** Real Android SQLite checks; every database path is isolated from the user's records. */
class MobileRecordsOpenInstrumentation : Instrumentation() {
    private val databases = mutableListOf<File>()
    private var mode = "all"

    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        mode = arguments?.getString("mode") ?: "all"
        start()
    }

    override fun onStart() {
        val openTests = listOf(
            "receiptReadCanOpenAndReopenNativeDatabase" to ::receiptRead,
            "contextReadSeesCommittedWalRecords" to ::contextRead,
            "missingDatabaseIsNotCreated" to ::missingDatabase,
            "unsupportedAgentStateCannotCommitOrAcknowledge" to ::unsupportedAgent,
        )
        val archiveTests = listOf(
            "archivePreservesRawHistoryWithoutLiveSideEffects" to ::archiveHistory,
            "archiveBatchRollsBackBeforeAcknowledgingInvalidHistory" to ::archiveRollback,
            "invalidObservationIsQuarantinedWithoutInventingHistory" to ::quarantineInvalid,
        )
        val tests = when (mode) {
            "open" -> openTests
            "archive" -> archiveTests
            else -> openTests + archiveTests
        }
        var failures = 0
        tests.forEachIndexed { index, (name, test) ->
            val status = Bundle().apply {
                putString("class", this@MobileRecordsOpenInstrumentation.javaClass.name)
                putString("test", name)
                putInt("numtests", tests.size)
                putInt("current", index + 1)
            }
            sendStatus(1, status)
            try {
                test()
                status.putString("stream", ".")
                sendStatus(0, status)
            } catch (failure: Throwable) {
                failures++
                status.putString("stack", failure.stackTraceToString())
                status.putString("stream", "\n$name: ${failure.stackTraceToString()}")
                sendStatus(-2, status)
            }
        }
        databases.forEach { SQLiteDatabase.deleteDatabase(it) }
        finish(if (failures == 0) Activity.RESULT_OK else Activity.RESULT_CANCELED,
            Bundle().apply {
                putString("stream", if (failures == 0) "\nOK (${tests.size} tests)\n"
                    else "\nFAILURES: $failures of ${tests.size} tests\n")
            })
    }

    private fun isolatedContext(): Context {
        // Instrumentation executes under the target UID, which cannot write the
        // test APK's cache directory. Only unique disposable target-cache files
        // are used; the application's real database path is never opened.
        val directory = File(targetContext.cacheDir, "mobile-records-instrumentation")
        check(directory.isDirectory || directory.mkdirs()) { "Could not create isolated fixture directory" }
        val file = File(directory, "mobile-records-open-${UUID.randomUUID()}.db")
        databases.add(file)
        return object : ContextWrapper(targetContext) {
            override fun getDatabasePath(name: String): File {
                check(name == "jarvis_mobile.db") { "Unexpected database requested: $name" }
                return file
            }
            override fun getSharedPreferences(name: String, mode: Int): SharedPreferences =
                error("Database regression must not access personal preferences: $name")
            override fun getSystemService(name: String): Any? =
                error("Database regression must not deliver alerts or change services: $name")
        }
    }

    private fun receiptRead() {
        val isolated = isolatedContext()
        SQLiteDatabase.openOrCreateDatabase(isolated.getDatabasePath("jarvis_mobile.db"), null).use { seed ->
            seed.execSQL("CREATE TABLE mobile_receipts(operation_id TEXT PRIMARY KEY,cost_nanos INTEGER NOT NULL DEFAULT 0,call_count INTEGER NOT NULL DEFAULT 0,estimated_tokens INTEGER NOT NULL DEFAULT 0)")
            seed.execSQL("INSERT INTO mobile_receipts(operation_id) VALUES(?)", arrayOf("event:saved"))
        }
        // Both calls hit the production open/setup path. execSQL(PRAGMA busy_timeout)
        // used to throw before either query could reach the receipt table.
        check(MobileRecords.applied(isolated, "saved")) { "Committed receipt was not readable" }
        check(!MobileRecords.applied(isolated, "missing")) { "Missing event was incorrectly acknowledged" }
    }

    private fun unsupportedAgent() {
        val isolated = isolatedContext()
        val file = isolated.getDatabasePath("jarvis_mobile.db")
        SQLiteDatabase.openOrCreateDatabase(file, null).close()
        val invalid = JSONObject().put("operation_id", "must-not-acknowledge")
            .put("agent", JSONObject().put("unsupported_state", JSONObject().put("private", "synthetic")))
            .put("budget", JSONObject().put("day", "2026-10-28").put("cost_nanos", 99))
        check(runCatching { MobileRecords.apply(isolated, invalid) }.exceptionOrNull() is IllegalArgumentException)
        check(runCatching { MobileRecords.apply(isolated, JSONObject(invalid.toString()).put("agent", org.json.JSONArray())) }.exceptionOrNull() is IllegalArgumentException)
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            check(scalar(db, "SELECT COUNT(*) FROM sqlite_master WHERE name IN ('mobile_usage','mobile_receipts')") == 0L)
        }
    }

    private fun contextRead() {
        val isolated = isolatedContext()
        SQLiteDatabase.openOrCreateDatabase(isolated.getDatabasePath("jarvis_mobile.db"), null).use { seed ->
            check(seed.enableWriteAheadLogging()) { "Fixture could not enable WAL" }
            seed.execSQL("CREATE TABLE reminders(id TEXT PRIMARY KEY,title TEXT,status TEXT,deleted_at TEXT)")
            MobileSqlStorage.ensure(seed)
            seed.beginTransaction()
            try {
                seed.execSQL("INSERT INTO reminders VALUES('active','Retained reminder','ACTIVE',NULL)")
                seed.execSQL("INSERT INTO reminders VALUES('paused','Paused reminder','PAUSED',NULL)")
                seed.execSQL("INSERT INTO reminders VALUES('completed','Completed reminder','COMPLETED',NULL)")
                seed.execSQL("INSERT INTO reminders VALUES('deleted','Deleted reminder','ACTIVE','2026-10-28T00:00:00Z')")
                MobileSqlStorage.put(seed, "dynamic_reminder_state", "active", JSONObject()
                    .put("origin_seen", "2026-10-28T08:00:00Z").put("journey_started", JSONObject.NULL), storedAt = 1)
                for (id in listOf("paused", "completed", "deleted")) {
                    MobileSqlStorage.put(seed, "dynamic_reminder_state", id, JSONObject().put("origin_seen", "excluded"), storedAt = 2)
                }
                // A global recent-state cap would lose the older active reminder.
                for (index in 0 until 35) {
                    MobileSqlStorage.put(seed, "dynamic_reminder_state", "orphan-$index", JSONObject().put("origin_seen", "orphan"), storedAt = 100L + index)
                }
                MobileSqlStorage.put(seed, "dynamic_reminder_state", "active", JSONObject().put("origin_seen", "other-owner"), uid = "other-owner", storedAt = 200)
                seed.setTransactionSuccessful()
            } finally {
                seed.endTransaction()
            }
            val result = MobileRecords.context(isolated, JSONObject())
            val reminders = result.getJSONObject("records").getJSONArray("reminders")
            check(reminders.length() == 1 && reminders.getJSONObject(0).getString("id") == "active") {
                "Native context failed to read the committed active WAL reminder"
            }
            check(result.getJSONObject("agent").has("domain") && result.has("budget")) {
                "Context envelope was not initialized"
            }
            val states = result.getJSONObject("agent").getJSONArray("records")
            val dynamic = (0 until states.length()).map { states.getJSONObject(it) }
                .filter { it.getString("table") == "dynamic_reminder_state" }
            check(dynamic.size == 1 && dynamic.single().getString("id") == "active" &&
                dynamic.single().getString("uid") == MobileSqlStorage.LOCAL_UID) {
                "Native context must forward only active, undeleted reminder state for the local owner"
            }
            val state = dynamic.single().getJSONObject("data")
            check(state.getString("origin_seen") == "2026-10-28T08:00:00Z" && state.isNull("journey_started")) {
                "Native context lost the older active reminder's departure continuity"
            }
        }
    }

    private fun missingDatabase() {
        val isolated = isolatedContext()
        val file = isolated.getDatabasePath("jarvis_mobile.db")
        val failure = runCatching { MobileRecords.applied(isolated, "missing") }.exceptionOrNull()
        check(failure is IllegalStateException && !file.exists()) {
            "Native worker must not create a replacement for missing phone storage"
        }
    }

    private fun archiveHistory() {
        val isolated = isolatedContext()
        val file = isolated.getDatabasePath("jarvis_mobile.db")
        SQLiteDatabase.openOrCreateDatabase(file, null).close()
        check(!MobileRecords.applied(isolated, "uninitialized"))
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { seed ->
            seed.execSQL("CREATE TABLE reminders(id TEXT PRIMARY KEY,title TEXT,status TEXT)")
            seed.execSQL("INSERT INTO reminders VALUES('live','Keep this reminder','ACTIVE')")
            MobileSqlStorage.put(seed, "mobility_sessions", "live", JSONObject().put("status", "ACTIVE"), domain = true, storedAt = 100)
            seed.execSQL("INSERT INTO mobile_usage VALUES('2026-10-28',25,2,400)")
            seed.execSQL("INSERT INTO mobile_receipts VALUES('event:already',25,2,400)")
        }
        val event = JSONObject().put("event_id", "archive-1").put("event_type", "ACTIVITY_ENTER")
            .put("occurred_at", "2026-10-20T08:00:00.000Z").put("timestamp", "2026-10-20T08:00:00.000Z")
            .put("activity", "WALKING").put("transition", "ENTER")
            .put("activity_evidence", "android_transition").put("activity_confidence", 91)
            .put("reported_activity", "WALKING").put("received_at", "2026-10-20T08:00:02Z")
            .put("location_status", "historical_event_fix")
            .put("location", JSONObject().put("latitude", 12.1).put("longitude", 77.2).put("accuracy_m", 8))
            .put("ambient_context", JSONObject().put("collected_at", "2026-10-20T08:00:00Z"))
            .put("telemetry_diagnostics", JSONObject().put("boot_count", 4).put("delivery_delay_ms", 2000))
        val duplicate = JSONObject(event.toString()).put("event_id", "already")
        check(MobileRecords.archiveContextEvents(isolated, listOf(event, duplicate)) == 1)
        check(MobileRecords.applied(isolated, "archive-1"))
        // A later retry must preserve the original history and existing charged receipt.
        check(MobileRecords.archiveContextEvents(isolated,
            listOf(JSONObject(event.toString()).put("activity", "IN_VEHICLE"), duplicate)) == 0)
        check(event.getString("activity") == "WALKING") { "Archive mutated the queued input" }
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            val records = MobileSqlStorage.records(db, "context_memory")
            check(records.length() == 1)
            val stored = records.getJSONObject(0)
            val saved = stored.getJSONObject("data")
            check(stored.getString("id").length == 64)
            check(scalar(db, "SELECT stored_at FROM record_context_memory") == 1792483200000L)
            check(saved.getString("timestamp") == "2026-10-20T08:00:00Z")
            check(saved.getString("activity") == "WALKING" && saved.getString("transition") == "ENTER")
            for (key in listOf("event_type", "activity_evidence", "activity_confidence", "reported_activity",
                "received_at", "ambient_context", "telemetry_diagnostics", "location_status")) {
                check(saved.get(key).toString() == event.get(key).toString()) { "Lost raw evidence: $key" }
            }
            check(saved.getJSONObject("gps").toString() == event.getJSONObject("location").toString())
            check(saved.getString("source") == "phone_observation" && saved.getBoolean("archived_locally"))
            check(saved.getJSONArray("contexts").length() == 0 && saved.isNull("mobility_session_id"))
            check(scalar(db, "SELECT COUNT(*) FROM mobile_notifications") == 0L)
            check(scalar(db, "SELECT COUNT(*) FROM domain_mobility_sessions") == 1L)
            check(scalar(db, "SELECT stored_at FROM domain_mobility_sessions WHERE row_key='live'") == 100L)
            check(scalar(db, "SELECT COUNT(*) FROM reminders WHERE id='live' AND status='ACTIVE'") == 1L)
            check(scalar(db, "SELECT cost_nanos FROM mobile_usage") == 25L)
            check(scalar(db, "SELECT call_count FROM mobile_usage") == 2L)
            check(scalar(db, "SELECT estimated_tokens FROM mobile_usage") == 400L)
            check(scalar(db, "SELECT cost_nanos FROM mobile_receipts WHERE operation_id='event:already'") == 25L)
            check(scalar(db, "SELECT cost_nanos FROM mobile_receipts WHERE operation_id='event:archive-1'") == 0L)
        }
    }

    private fun archiveRollback() {
        val isolated = isolatedContext()
        val file = isolated.getDatabasePath("jarvis_mobile.db")
        SQLiteDatabase.openOrCreateDatabase(file, null).close()
        val valid = JSONObject().put("event_id", "rollback-first").put("occurred_at", "2026-10-20T08:00:00Z")
            .put("activity", "UNKNOWN").put("event_type", "CONTEXT_CHECKPOINT")
        val invalid = JSONObject().put("event_id", "rollback-invalid").put("occurred_at", "not-a-time")
        check(runCatching { MobileRecords.archiveContextEvents(isolated, listOf(valid, invalid)) }.isFailure)
        check(!MobileRecords.applied(isolated, "rollback-first"))
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            check(scalar(db, "SELECT COUNT(*) FROM record_context_memory") == 0L)
            check(scalar(db, "SELECT COUNT(*) FROM mobile_receipts") == 0L)
        }
    }

    private fun scalar(db: SQLiteDatabase, sql: String): Long =
        db.rawQuery(sql, null).use { cursor -> check(cursor.moveToFirst()); cursor.getLong(0) }

    private fun quarantineInvalid() {
        val isolated = isolatedContext()
        val file = isolated.getDatabasePath("jarvis_mobile.db")
        SQLiteDatabase.openOrCreateDatabase(file, null).close()
        check(!MobileRecords.applied(isolated, "quarantine-initialize"))
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            db.execSQL("INSERT INTO mobile_usage VALUES('2026-10-28',47,3,600)")
            db.execSQL("INSERT INTO mobile_receipts VALUES('event:already-invalid',9,1,150)")
            MobileSqlStorage.put(db, "mobility_sessions", "future", JSONObject().put("status", "ACTIVE"), domain = true, storedAt = 999)
        }
        val invalid = JSONObject().put("event_id", "invalid-time").put("occurred_at", "bad-time")
            .put("timestamp", "bad-time").put("activity", "WALKING").put("transition", "ENTER")
            .put("activity_evidence", "android_transition").put("source", "original-phone-source")
            .put("location", JSONObject().put("latitude", 12.1).put("longitude", 77.2))
        val already = JSONObject(invalid.toString()).put("event_id", "already-invalid")
        check(MobileRecords.archiveInvalidContextEvents(isolated, listOf(invalid, already)) == 1)
        check(MobileRecords.applied(isolated, "invalid-time"))
        check(MobileRecords.archiveInvalidContextEvents(isolated,
            listOf(JSONObject(invalid.toString()).put("activity", "IN_VEHICLE"))) == 0)
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            val quarantined = MobileSqlStorage.records(db, "context_processing_errors")
            check(quarantined.length() == 1)
            val saved = quarantined.getJSONObject(0).getJSONObject("data")
            check(saved.getJSONObject("original_payload").toString() == invalid.toString())
            check(saved.getString("source") == "phone_context_quarantine")
            check(saved.getString("reason") == "invalid_observation_time")
            check(!saved.has("timestamp") && !saved.has("activity"))
            check(scalar(db, "SELECT stored_at FROM record_context_processing_errors") == 0L)
            check(scalar(db, "SELECT COUNT(*) FROM record_context_memory") == 0L)
            check(scalar(db, "SELECT COUNT(*) FROM mobile_notifications") == 0L)
            check(scalar(db, "SELECT stored_at FROM domain_mobility_sessions WHERE row_key='future'") == 999L)
            check(scalar(db, "SELECT cost_nanos FROM mobile_usage") == 47L)
            check(scalar(db, "SELECT call_count FROM mobile_usage") == 3L)
            check(scalar(db, "SELECT estimated_tokens FROM mobile_usage") == 600L)
            check(scalar(db, "SELECT cost_nanos FROM mobile_receipts WHERE operation_id='event:already-invalid'") == 9L)
            check(scalar(db, "SELECT cost_nanos FROM mobile_receipts WHERE operation_id='event:invalid-time'") == 0L)
        }
    }

}
