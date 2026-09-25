package com.jarvis.jarvis_collector

import android.Manifest
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.SystemClock
import android.os.ParcelUuid
import android.os.PowerManager
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Short snapshots at meaningful changes. Never uploads names or MAC addresses. */
object AmbientContextCapture {
    private val scanLock = Any()
    private var scanning = false
    private var lastScanStarted = -30_000L
    private var cachedScan: JSONObject? = null
    private var cachedAt = 0L

    private fun permitted(c: Context, permission: String) = c.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    @Synchronized fun identity(c: Context, value: String): String {
        val p = c.getSharedPreferences("jarvis_ambient", Context.MODE_PRIVATE)
        var salt = p.getString("salt", null)
        if (salt == null) {
            salt = UUID.randomUUID().toString()
            check(p.edit().putString("salt", salt).commit())
        }
        return MessageDigest.getInstance("SHA-256").digest("$salt:$value".toByteArray())
            .joinToString("") { "%02x".format(it) }
    }

    fun needsCloudIdentity(c: Context): Boolean =
        !c.getSharedPreferences("jarvis_ambient", Context.MODE_PRIVATE).getBoolean("cloud_identity", false)

    @Synchronized fun restoreCloudIdentity(c: Context, salt: String) {
        if (!salt.matches(Regex("[a-f0-9]{64}"))) return
        check(c.getSharedPreferences("jarvis_ambient", Context.MODE_PRIVATE).edit()
            .putString("salt", salt).putBoolean("cloud_identity", true).commit())
    }

    fun capture(c: Context, scanMillis: Long = 0): JSONObject {
        val capturedAt = ContextEventQueue.occurredAt()
        return JSONObject().put("collected_at", capturedAt)
            .put("wifi", wifi(c)).put("bluetooth", bluetooth(c, scanMillis))
    }

    @Suppress("DEPRECATION")
    private fun wifi(c: Context): JSONObject {
        val result = JSONObject().put("status", "unavailable").put("nearby", JSONArray())
        if (!permitted(c, Manifest.permission.ACCESS_FINE_LOCATION)) return result.put("status", "location_permission_required")
        return try {
            val manager = c.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            if (!manager.isWifiEnabled) return result.put("status", "disabled")
            val connection = manager.connectionInfo
            val bssid = connection?.bssid
            if (bssid != null && bssid != "02:00:00:00:00:00" && bssid != "00:00:00:00:00:00") {
                result.put("connected", JSONObject().put("id", identity(c, "wifi:$bssid"))
                    .put("rssi", connection.rssi.coerceIn(-150, 20)).put("age_ms", 0))
            }
            val now = SystemClock.elapsedRealtime()
            val nearby = manager.scanResults.filter { now - it.timestamp / 1000 in 0..120_000 }
                .sortedByDescending { it.level }.take(24)
            result.put("nearby", JSONArray().apply {
                nearby.forEach { scan -> put(JSONObject().put("id", identity(c, "wifi:${scan.BSSID}"))
                    .put("rssi", scan.level.coerceIn(-150, 20)).put("age_ms", now - scan.timestamp / 1000)) }
            })
            result.put("status", if (result.has("connected") || nearby.isNotEmpty()) "available" else "no_fresh_results")
        } catch (_: SecurityException) { result.put("status", "permission_required") }
          catch (_: Exception) { result.put("status", "unavailable") }
    }

    @Suppress("MissingPermission")
    private fun bluetooth(c: Context, scanMillis: Long): JSONObject {
        val result = JSONObject().put("status", "unavailable").put("connected", JSONArray()).put("nearby", JSONArray())
        if (Build.VERSION.SDK_INT >= 31 && !permitted(c, Manifest.permission.BLUETOOTH_CONNECT)) {
            return result.put("status", "nearby_permission_required")
        }
        return try {
            val manager = c.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
            val adapter = manager.adapter ?: return result.put("status", "unsupported")
            if (!adapter.isEnabled) return result.put("status", "disabled")
            val connected = JSONArray()
            manager.getConnectedDevices(BluetoothProfile.GATT).take(24).forEach { device ->
                connected.put(JSONObject().put("id", identity(c, "bt:${device.address}")))
            }
            result.put("connected", connected)
            val canScan = permitted(c, Manifest.permission.ACCESS_FINE_LOCATION) &&
                (Build.VERSION.SDK_INT < 31 || permitted(c, Manifest.permission.BLUETOOTH_SCAN))
            if (!canScan) return result.put("status", "scan_permission_required")
            if (scanMillis <= 0) return result.put("status", "connected_snapshot")
            val scanner = adapter.bluetoothLeScanner ?: return result.put("status", "scanner_unavailable")
            // Broadcast capture and upload workers can overlap. Share recent
            // evidence instead of exhausting Android's scan-registration quota.
            synchronized(scanLock) {
                val now = SystemClock.elapsedRealtime()
                val previous = cachedScan
                if (previous != null && now - cachedAt <= 30_000) {
                    val copy = JSONObject(previous.toString())
                    val rows = copy.optJSONArray("nearby") ?: JSONArray()
                    for (i in 0 until rows.length()) {
                        val row = rows.getJSONObject(i)
                        row.put("age_ms", row.optLong("age_ms") + now - cachedAt)
                    }
                    copy.put("connected", connected)
                    return copy
                }
                if (scanning) return result.put("status", "scan_in_progress")
                if (now - lastScanStarted < 30_000) return result.put("status", "scan_deferred")
                scanning = true
                lastScanStarted = now
            }
            val seen = ConcurrentHashMap<String, Pair<Int, Long>>()
            val finished = CountDownLatch(1)
            var failure: Int? = null
            val callback = object : ScanCallback() {
                override fun onScanResult(callbackType: Int, scan: ScanResult) {
                    if (seen.size < 24) seen[identity(c, "bt:${scan.device.address}")] =
                        scan.rssi.coerceIn(-150, 20) to SystemClock.elapsedRealtime()
                }
                override fun onScanFailed(errorCode: Int) {
                    failure = errorCode
                    Log.w("JarvisAmbient", "Bluetooth snapshot scan failed: $errorCode")
                    finished.countDown()
                }
            }
            try {
                val interactive = (c.getSystemService(Context.POWER_SERVICE) as PowerManager).isInteractive
                // Android suspends unfiltered scans with the screen off. Use
                // actual location-beacon filters for those bounded snapshots.
                val filters = if (interactive) null else listOf(
                    ScanFilter.Builder().setManufacturerData(0x004c, byteArrayOf(0x02, 0x15)).build(),
                    ScanFilter.Builder().setServiceUuid(ParcelUuid(UUID.fromString("0000feaa-0000-1000-8000-00805f9b34fb"))).build(),
                )
                result.put("scan_scope", if (interactive) "nearby_devices" else "location_beacons")
                try {
                    scanner.startScan(filters, ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_POWER).build(), callback)
                    finished.await(scanMillis.coerceAtMost(2500), TimeUnit.MILLISECONDS)
                } finally { runCatching { scanner.stopScan(callback) } }
                val now = SystemClock.elapsedRealtime()
                result.put("nearby", JSONArray().apply {
                    seen.entries.sortedByDescending { it.value.first }.forEach {
                        put(JSONObject().put("id", it.key).put("rssi", it.value.first)
                            .put("age_ms", now - it.value.second))
                    }
                })
                if (failure != null) result.put("scan_error_code", failure)
                result.put("status", if (failure != null) "scan_unavailable" else if (seen.isEmpty()) "no_nearby_results" else "available")
            } finally {
                synchronized(scanLock) {
                    cachedScan = JSONObject(result.toString())
                    cachedAt = SystemClock.elapsedRealtime()
                    scanning = false
                }
            }
        } catch (_: SecurityException) { result.put("status", "nearby_permission_required") }
          catch (_: Exception) { result.put("status", "unavailable") }
    }
}
