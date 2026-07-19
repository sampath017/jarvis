package com.jarvis.edge.ui

import android.Manifest
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.google.android.gms.location.ActivityRecognition
import com.google.android.gms.location.ActivityTransition
import com.google.android.gms.location.ActivityTransitionRequest
import com.google.android.gms.location.DetectedActivity
import com.jarvis.edge.data.repository.ContextRepository
import com.jarvis.edge.data.repository.FirestoreRepository
import com.jarvis.edge.data.repository.UserRepository
import com.jarvis.edge.domain.sensors.ActivityReceiver
import com.jarvis.edge.ui.auth.AuthScreen
import com.jarvis.edge.ui.home.JarvisHomeScreen
import com.jarvis.edge.ui.theme.JarvisTheme

class MainActivity : ComponentActivity() {

    private val userRepository = UserRepository()
    private val firestoreRepository = FirestoreRepository()
    private lateinit var contextRepository: ContextRepository

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { _ ->
        setupActivityTransitions()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        contextRepository = ContextRepository(this)

        setContent {
            JarvisTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    val currentUser by userRepository.currentUser.collectAsState()
                    val isResolved = currentUser != null || !userRepository.isPending()

                    LaunchedEffect(Unit) {
                        checkAndRequestPermissions()
                    }

                    if (isResolved) {
                        val startDest = if (currentUser != null) "home" else "auth"
                        val navController = rememberNavController()

                        LaunchedEffect(currentUser?.uid) {
                            val destination = if (currentUser == null) "auth" else "home"
                            if (navController.currentDestination?.route != destination) {
                                navController.navigate(destination) {
                                    popUpTo(navController.graph.startDestinationId) { inclusive = true }
                                    launchSingleTop = true
                                }
                            }
                        }

                        NavHost(navController = navController, startDestination = startDest) {
                            composable("auth") {
                                AuthScreen(
                                    userRepository = userRepository,
                                    onAuthSuccess = {
                                        navController.navigate("home") {
                                            popUpTo("auth") { inclusive = true }
                                        }
                                    }
                                )
                            }

                            composable("home") {
                                currentUser?.let { user ->
                                    JarvisHomeScreen(
                                        uid = user.uid,
                                        userDisplayName = user.displayName,
                                        firestoreRepository = firestoreRepository,
                                        contextRepository = contextRepository,
                                        onSignOut = userRepository::signOut
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private fun checkAndRequestPermissions() {
        val permissions = buildList {
            add(Manifest.permission.ACCESS_FINE_LOCATION)
            add(Manifest.permission.ACCESS_COARSE_LOCATION)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                add(Manifest.permission.ACTIVITY_RECOGNITION)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                add(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        val missing = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (missing.isEmpty()) {
            setupActivityTransitions()
        } else {
            requestPermissionLauncher.launch(missing.toTypedArray())
        }
    }

    @android.annotation.SuppressLint("MissingPermission")
    private fun setupActivityTransitions() {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACTIVITY_RECOGNITION) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        val transitions = listOf(
            ActivityTransition.Builder()
                .setActivityType(DetectedActivity.IN_VEHICLE)
                .setActivityTransition(ActivityTransition.ACTIVITY_TRANSITION_ENTER)
                .build(),
            ActivityTransition.Builder()
                .setActivityType(DetectedActivity.IN_VEHICLE)
                .setActivityTransition(ActivityTransition.ACTIVITY_TRANSITION_EXIT)
                .build(),
            ActivityTransition.Builder()
                .setActivityType(DetectedActivity.WALKING)
                .setActivityTransition(ActivityTransition.ACTIVITY_TRANSITION_ENTER)
                .build(),
            ActivityTransition.Builder()
                .setActivityType(DetectedActivity.STILL)
                .setActivityTransition(ActivityTransition.ACTIVITY_TRANSITION_ENTER)
                .build()
        )

        try {
            ActivityRecognition.getClient(this)
                .requestActivityTransitionUpdates(
                    ActivityTransitionRequest(transitions),
                    activityTransitionPendingIntent()
                )
                .addOnFailureListener { exception ->
                    Log.e(TAG, "Unable to register activity transitions", exception)
                }
        } catch (exception: SecurityException) {
            Log.e(TAG, "Activity transition permission was rejected", exception)
        }
    }

    private fun activityTransitionPendingIntent(): PendingIntent {
        val intent = Intent(this, ActivityReceiver::class.java).apply {
            action = ACTION_PROCESS_ACTIVITY_TRANSITIONS
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0
        return PendingIntent.getBroadcast(this, 0, intent, flags)
    }

    companion object {
        private const val TAG = "MainActivity"
        const val ACTION_PROCESS_ACTIVITY_TRANSITIONS =
            "com.jarvis.edge.ACTION_PROCESS_ACTIVITY_TRANSITIONS"
    }
}
