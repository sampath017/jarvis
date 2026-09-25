package com.jarvis.jarvis_collector

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log

/** Re-registers Play Services transitions after reboot or package replacement. */
class MonitoringRestartReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED &&
            intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        if (!ActivityRecognitionRegistrar.isEnabled(context)) return
        if (Build.VERSION.SDK_INT >= 29 &&
            context.checkSelfPermission(Manifest.permission.ACTIVITY_RECOGNITION) != PackageManager.PERMISSION_GRANTED) return
        val pending = goAsync()
        ActivityRecognitionRegistrar.register(context,
            onSuccess = { pending.finish() },
            onFailure = { error ->
                Log.w("JarvisRestart", "Activity registration deferred until app opens", error)
                pending.finish()
            },
        )
    }
}
