package com.jarvis.jarvis_collector

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager
import android.bluetooth.BluetoothDevice

/** Phone-call and Bluetooth connection changes share the durable event outbox. */
class SituationChangeReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (!ActivityRecognitionRegistrar.isEnabled(context)) return
        val type = if (intent.action == TelephonyManager.ACTION_PHONE_STATE_CHANGED) {
            val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
            if (state == TelephonyManager.EXTRA_STATE_RINGING) return
            val p = context.getSharedPreferences("jarvis_call_state", Context.MODE_PRIVATE)
            val previous = p.getString("state", TelephonyManager.EXTRA_STATE_IDLE)
            if (state == previous) return
            check(p.edit().putString("state", state).commit())
            if (state == TelephonyManager.EXTRA_STATE_OFFHOOK) "CALL_START"
            else if (previous == TelephonyManager.EXTRA_STATE_OFFHOOK) "CALL_END" else return
        } else if (intent.action == BluetoothDevice.ACTION_ACL_CONNECTED) "BLUETOOTH_CONNECTED"
        else "BLUETOOTH_DISCONNECTED"
        // A call overlays motion. Never replace walking with a call label.
        val activity = ContextEventQueue.currentActivity(context).ifEmpty { "UNKNOWN" }
        ContextEventQueue.add(context, ContextEventQueue.newEvent(type, activity, if (type == "CALL_END") "EXIT" else "ENTER"))
    }
}
