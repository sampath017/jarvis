package com.jarvis.jarvis_collector

import android.accounts.Account
import android.accounts.AccountManager
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.view.WindowManager
import com.google.android.gms.auth.GoogleAuthUtil
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.AccountPicker
import com.google.android.gms.common.api.Scope
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.security.SecureRandom

/** Google consent is only launched by Connect. Access tokens are never persisted. */
class GoogleAccountAuthorization(private val activity: MainActivity, messenger: BinaryMessenger, private val provider: String = "calendar") {
    private val prefs = activity.getSharedPreferences("jarvis_google_$provider", Context.MODE_PRIVATE)
    private val records = if (provider == "drive") activity.getSharedPreferences("jarvis_file_memory", Context.MODE_PRIVATE) else prefs
    private val providerName = if (provider == "drive") "Google Drive" else "Google Calendar"
    private val client = Identity.getAuthorizationClient(activity)
    private val scopes = if (provider == "drive") listOf(Scope("https://www.googleapis.com/auth/drive.file"), Scope("https://www.googleapis.com/auth/drive.readonly"), Scope("https://www.googleapis.com/auth/forms.responses.readonly")) else
        listOf(Scope("https://www.googleapis.com/auth/calendar.events"), Scope("https://www.googleapis.com/auth/calendar.calendarlist.readonly"))
    private val pickerCode = if (provider == "drive") 8720 else 8710
    private val consentCode = pickerCode + 1
    private var pending: MethodChannel.Result? = null
    private var selectedEmail: String? = null
    private var token: String? = null
    private var tokenEmail: String? = null
    private var tokenAt = 0L
    private var returnsAuthorization = false

    init {
        // Existing per-file grants cannot silently become whole-Drive grants.
        if (provider == "drive" && prefs.getBoolean("connected", false) && prefs.getInt("scopeVersion", 0) < 3) {
            prefs.edit().putBoolean("connected", false).putBoolean("needsReconnect", true).commit()
        }
        MethodChannel(messenger, "com.jarvis/google_$provider").setMethodCallHandler { call, result ->
            when (call.method) {
                "indexingScreen" -> {
                    if (call.arguments == true) activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    else activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    result.success(true)
                }
                "status" -> result.success(mapOf("connected" to prefs.getBoolean("connected", false),
                    "email" to prefs.getString("email", ""), "calendarId" to prefs.getString("calendarId", "primary"),
                    "needsReconnect" to prefs.getBoolean("needsReconnect", false)))
                "connect" -> {
                    if (pending != null) result.error("BUSY", "Google authorization is already open.", null)
                    else {
                        pending = result
                        returnsAuthorization = true
                        selectedEmail = call.argument<String>("preferredEmail") ?: "sampathkovvali@gmail.com"
                        authorize(true)
                    }
                }
                "restoreConnection" -> {
                    if (prefs.getBoolean("userDisconnected", false) || prefs.getBoolean("connected", false)) result.success(null)
                    else if (pending != null) result.error("BUSY", "Google authorization is already open.", null)
                    else {
                        pending = result
                        returnsAuthorization = true
                        selectedEmail = prefs.getString("email", null)?.takeIf { it.isNotBlank() }
                            ?: call.argument<String>("preferredEmail") ?: "sampathkovvali@gmail.com"
                        // Existing grants only: never open an account picker or consent UI on launch.
                        authorize(false)
                    }
                }
                "token" -> {
                    val email = prefs.getString("email", "") ?: ""
                    if (!prefs.getBoolean("connected", false) || email.isEmpty()) result.error("DISCONNECTED", "Connect $providerName in Settings.", null)
                    else if (pending != null) result.error("BUSY", "Google authorization is already open.", null)
                    else if (token != null && tokenEmail == email && System.currentTimeMillis() - tokenAt < 45 * 60 * 1000) result.success(token)
                    else { pending = result; returnsAuthorization = false; selectedEmail = email; authorize(false) }
                }
                "saveConnection" -> {
                    // Called only after a successful Calendar API request proves scope access.
                    val email = call.argument<String>("email") ?: ""
                    if (token == null || selectedEmail != email) result.error("INVALID_ACCOUNT", "Reconnect $providerName.", null)
                    else { prefs.edit().putBoolean("connected", true).putString("email", email)
                        .putBoolean("needsReconnect", false).putBoolean("userDisconnected", false)
                        .putInt("scopeVersion", if (provider == "drive") 3 else 2)
                        .putString("calendarId", call.argument<String>("calendarId") ?: "primary").commit(); result.success(true) }
                }
                "selectCalendar" -> { prefs.edit().putString("calendarId", call.arguments as String).commit(); result.success(true) }
                "disconnect" -> {
                    fail("CANCELLED", "$providerName was disconnected.")
                    token = null; tokenEmail = null; tokenAt = 0; selectedEmail = null
                    prefs.edit().clear().putBoolean("userDisconnected", true).commit()
                    // No further reads/writes are possible locally; account grants can also be revoked in Google settings.
                    result.success(true)
                }
                "accessRequired" -> { markAccessRequired(); result.success(true) }
                "sessionKey" -> {
                    val keyStore = if (provider == "drive") records else prefs
                    var key = keyStore.getString("sessionKey", null)
                    if (key == null) {
                        val bytes = ByteArray(32); SecureRandom().nextBytes(bytes)
                        key = bytes.joinToString("") { "%02x".format(it.toInt() and 255) }
                        if (!keyStore.edit().putString("sessionKey", key).commit()) {
                            result.error("STORAGE", "Cannot safely retain file memory authorization.", null)
                            return@setMethodCallHandler
                        }
                    }
                    result.success(key)
                }
                "readRecord" -> result.success(records.getString("record_" + call.arguments.toString(), null))
                "writeRecord" -> {
                    val key = call.argument<String>("key") ?: ""
                    val value = call.argument<String>("value") ?: ""
                    if (!records.edit().putString("record_" + key, value).commit()) result.error("STORAGE", "Cannot safely save this operation.", null)
                    else result.success(true)
                }
                "clearToken" -> {
                    val previous = token; token = null; tokenAt = 0
                    Thread {
                        try { if (previous != null) GoogleAuthUtil.clearToken(activity.applicationContext, previous) } catch (_: Exception) {}
                        activity.runOnUiThread { result.success(true) }
                    }.start()
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun authorize(interactive: Boolean) {
        val email = selectedEmail ?: return fail("ACCOUNT", "Choose your Google account.")
        val request = pending ?: return
        client.authorize(AuthorizationRequest.builder().setAccount(Account(email, "com.google"))
            .setRequestedScopes(scopes).build())
            .addOnSuccessListener { response ->
                if (pending !== request || selectedEmail != email) return@addOnSuccessListener
                if (response.hasResolution()) {
                    if (!interactive) fail("CONSENT_REQUIRED", "Reconnect $providerName in Settings to renew permission.")
                    else try { activity.startIntentSenderForResult(response.pendingIntent!!.intentSender, consentCode, null, 0, 0, 0) }
                        catch (_: Exception) { fail("CONSENT_FAILED", "Could not open Google consent.") }
                } else complete(response, returnsAuthorization)
            }
            .addOnFailureListener {
                if (pending === request) fail("GOOGLE_AUTH", "Google authorization failed. Check the API and Android OAuth client for this app's signing certificate. ${it.javaClass.simpleName}")
            }
    }

    private fun complete(response: AuthorizationResult, connecting: Boolean) {
        if (pending == null) return
        if (response.accessToken.isNullOrEmpty() || !response.grantedScopes.containsAll(scopes.map { it.scopeUri })) {
            fail("SCOPES_REQUIRED", "$providerName permissions are required. No connection was saved."); return
        }
        token = response.accessToken; tokenEmail = selectedEmail; tokenAt = System.currentTimeMillis()
        val result = pending; pending = null
        if (connecting) result?.success(mapOf("token" to token, "email" to selectedEmail)) else result?.success(token)
    }

    fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != pickerCode && requestCode != consentCode) return
        if (resultCode != Activity.RESULT_OK || data == null) { fail("CANCELLED", "$providerName connection cancelled."); return }
        if (requestCode == pickerCode) {
            selectedEmail = data.getStringExtra(AccountManager.KEY_ACCOUNT_NAME)
            authorize(true)
        } else try { complete(client.getAuthorizationResultFromIntent(data), true) }
            catch (_: Exception) { fail("CONSENT_FAILED", "$providerName consent was not completed.") }
    }

    private fun markAccessRequired() {
        val wasConnected = prefs.getBoolean("connected", false) || prefs.getBoolean("needsReconnect", false)
        token = null; tokenEmail = null; tokenAt = 0
        prefs.edit().putBoolean("connected", false).putBoolean("needsReconnect", wasConnected).commit()
    }

    private fun fail(code: String, message: String) {
        if (code == "CONSENT_REQUIRED" || code == "SCOPES_REQUIRED") markAccessRequired()
        val result = pending; pending = null; result?.error(code, message, null)
    }
}
