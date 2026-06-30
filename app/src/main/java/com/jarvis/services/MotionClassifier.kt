package com.jarvis.services

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.sqrt

/**
 * MotionClassifier captures raw IMU data in short bursts and extracts
 * features for vehicle fingerprinting.
 *
 * Based on the Jarvis Simulation doc:
 * - Samples accelerometer + gyroscope at ~50Hz
 * - Runs short bursts (3-10 seconds) triggered by Activity Recognition
 * - Extracts time-domain and frequency-domain features
 * - Returns a classification result with confidence
 */
class MotionClassifier(private val context: Context) {

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    private val linearAccel = sensorManager.getDefaultSensor(Sensor.TYPE_LINEAR_ACCELERATION)

    private val _classificationResult = MutableStateFlow<ClassificationResult?>(null)
    val classificationResult: StateFlow<ClassificationResult?> = _classificationResult.asStateFlow()

    private val _isClassifying = MutableStateFlow(false)
    val isClassifying: StateFlow<Boolean> = _isClassifying.asStateFlow()

    // Buffers for burst capture
    private val accelBuffer = mutableListOf<FloatArray>()
    private val gyroBuffer = mutableListOf<FloatArray>()
    private val linearAccelBuffer = mutableListOf<FloatArray>()
    private val timestampBuffer = mutableListOf<Long>()

    private var sensorListener: SensorEventListener? = null

    /**
     * Run a short IMU burst for vehicle classification.
     * @param durationMs Duration of IMU capture in milliseconds (default 10 seconds for full, 3-5 for verification)
     */
    suspend fun runClassificationBurst(durationMs: Long = 10_000L): ClassificationResult {
        _isClassifying.value = true
        accelBuffer.clear()
        gyroBuffer.clear()
        linearAccelBuffer.clear()
        timestampBuffer.clear()

        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                when (event.sensor.type) {
                    Sensor.TYPE_ACCELEROMETER -> {
                        accelBuffer.add(event.values.clone())
                        timestampBuffer.add(event.timestamp)
                    }
                    Sensor.TYPE_GYROSCOPE -> {
                        gyroBuffer.add(event.values.clone())
                    }
                    Sensor.TYPE_LINEAR_ACCELERATION -> {
                        linearAccelBuffer.add(event.values.clone())
                    }
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
        }

        sensorListener = listener

        // Register at ~50Hz (20ms delay = SENSOR_DELAY_GAME)
        accelerometer?.let {
            sensorManager.registerListener(listener, it, SensorManager.SENSOR_DELAY_GAME)
        }
        gyroscope?.let {
            sensorManager.registerListener(listener, it, SensorManager.SENSOR_DELAY_GAME)
        }
        linearAccel?.let {
            sensorManager.registerListener(listener, it, SensorManager.SENSOR_DELAY_GAME)
        }

        // Wait for burst duration
        delay(durationMs)

        // Unregister sensors
        sensorManager.unregisterListener(listener)
        sensorListener = null

        // Extract features and classify
        val result = extractFeaturesAndClassify()
        _classificationResult.value = result
        _isClassifying.value = false

        return result
    }

    /**
     * Run a short verification burst (3-5 seconds) to confirm vehicle identity.
     */
    suspend fun runVerificationBurst(expectedVehicle: String): ClassificationResult {
        val result = runClassificationBurst(durationMs = 3_000L)
        return result.copy(
            isVerification = true,
            expectedVehicle = expectedVehicle,
        )
    }

    /**
     * Extract time-domain and frequency-domain features from captured IMU data.
     * Then classify the motion pattern.
     */
    private fun extractFeaturesAndClassify(): ClassificationResult {
        if (accelBuffer.size < 50) {
            return ClassificationResult(
                vehicleIdentity = "unknown",
                confidence = 0f,
                motionType = "insufficient_data",
                sampleCount = accelBuffer.size,
            )
        }

        // Time-domain features from accelerometer
        val magnitudes = accelBuffer.map { v ->
            sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        }
        val meanMag = magnitudes.average().toFloat()
        val stdMag = standardDeviation(magnitudes)
        val maxMag = magnitudes.maxOrNull() ?: 0f
        val minMag = magnitudes.minOrNull() ?: 0f
        val rangeMag = maxMag - minMag

        // Gyro energy
        val gyroEnergy = if (gyroBuffer.isNotEmpty()) {
            gyroBuffer.map { v ->
                v[0] * v[0] + v[1] * v[1] + v[2] * v[2]
            }.average().toFloat()
        } else 0f

        // Simple frequency analysis (zero-crossing rate as a proxy for dominant frequency)
        val zcr = zeroCrossingRate(magnitudes.map { it - meanMag })

        // Simple rule-based classifier (placeholder for future TFLite model)
        // Hunter 350 characteristics: high vibration amplitude, low-frequency dominant, high gyro energy
        val features = MotionFeatures(
            meanAccelMagnitude = meanMag,
            stdAccelMagnitude = stdMag,
            rangeAccelMagnitude = rangeMag,
            gyroEnergy = gyroEnergy,
            zeroCrossingRate = zcr,
            sampleCount = accelBuffer.size,
            durationMs = if (timestampBuffer.size >= 2)
                (timestampBuffer.last() - timestampBuffer.first()) / 1_000_000L
            else 0L,
        )

        return classifyFromFeatures(features)
    }

    /**
     * Rule-based classification.
     * This will be replaced by a TFLite model in Stage 3.
     */
    private fun classifyFromFeatures(features: MotionFeatures): ClassificationResult {
        // High vibration + high gyro = motorcycle
        // Lower vibration + lower gyro = car
        // Very low = still/walking

        val isHighVibration = features.stdAccelMagnitude > 1.5f
        val isMediumVibration = features.stdAccelMagnitude > 0.5f
        val isHighGyro = features.gyroEnergy > 0.3f

        return when {
            isHighVibration && isHighGyro -> ClassificationResult(
                vehicleIdentity = "Hunter_350",
                confidence = 0.85f + (features.stdAccelMagnitude / 10f).coerceAtMost(0.09f),
                motionType = "motorcycle",
                sampleCount = features.sampleCount,
                features = features,
            )
            isMediumVibration && !isHighGyro -> ClassificationResult(
                vehicleIdentity = "car_generic",
                confidence = 0.70f,
                motionType = "car",
                sampleCount = features.sampleCount,
                features = features,
            )
            isMediumVibration -> ClassificationResult(
                vehicleIdentity = "two_wheeler_generic",
                confidence = 0.60f,
                motionType = "two_wheeler",
                sampleCount = features.sampleCount,
                features = features,
            )
            else -> ClassificationResult(
                vehicleIdentity = "unknown",
                confidence = 0.3f,
                motionType = "low_motion",
                sampleCount = features.sampleCount,
                features = features,
            )
        }
    }

    fun stopClassification() {
        sensorListener?.let { sensorManager.unregisterListener(it) }
        sensorListener = null
        _isClassifying.value = false
    }

    private fun standardDeviation(values: List<Float>): Float {
        val mean = values.average()
        val variance = values.map { (it - mean) * (it - mean) }.average()
        return sqrt(variance).toFloat()
    }

    private fun zeroCrossingRate(values: List<Float>): Float {
        if (values.size < 2) return 0f
        var crossings = 0
        for (i in 1 until values.size) {
            if ((values[i] >= 0 && values[i - 1] < 0) || (values[i] < 0 && values[i - 1] >= 0)) {
                crossings++
            }
        }
        return crossings.toFloat() / values.size
    }
}

data class ClassificationResult(
    val vehicleIdentity: String,
    val confidence: Float,
    val motionType: String,
    val sampleCount: Int,
    val features: MotionFeatures? = null,
    val isVerification: Boolean = false,
    val expectedVehicle: String? = null,
)

data class MotionFeatures(
    val meanAccelMagnitude: Float,
    val stdAccelMagnitude: Float,
    val rangeAccelMagnitude: Float,
    val gyroEnergy: Float,
    val zeroCrossingRate: Float,
    val sampleCount: Int,
    val durationMs: Long,
)
