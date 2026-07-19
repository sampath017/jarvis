package com.jarvis.edge.domain.sensors

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import com.google.android.gms.location.ActivityTransitionResult
import com.jarvis.edge.service.TransitionService

class ActivityReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (ActivityTransitionResult.hasResult(intent)) {
            val result = ActivityTransitionResult.extractResult(intent) ?: return
            
            for (event in result.transitionEvents) {
                val serviceIntent = Intent(context, TransitionService::class.java).apply {
                    putExtra(TransitionService.EXTRA_ACTIVITY_TYPE, event.activityType)
                    putExtra(TransitionService.EXTRA_TRANSITION_TYPE, event.transitionType)
                }

                try {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        context.startForegroundService(serviceIntent)
                    } else {
                        context.startService(serviceIntent)
                    }
                } catch (exception: Exception) {
                    Log.e(TAG, "Unable to start transition processing", exception)
                }
            }
        }
    }

    companion object {
        private const val TAG = "ActivityReceiver"
    }
}
