package com.jarvis.edge.domain.sensors

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import com.jarvis.edge.domain.features.FeatureExtractor
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.ArrayList
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class SensorSampler(context: Context) : SensorEventListener {

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val accelSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroSensor = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    private val accelX = ArrayList<Double>()
    private val accelY = ArrayList<Double>()
    private val accelZ = ArrayList<Double>()
    private val gyroX = ArrayList<Double>()
    private val gyroY = ArrayList<Double>()
    private val gyroZ = ArrayList<Double>()

    private var onComplete: ((FeatureExtractor.AxisRawData) -> Unit)? = null
    private var targetSamples = 500 // 10 seconds * 50Hz
    private var isSampling = false
    private var requestedSamplingRateHz = 50

    suspend fun collectBurst(durationSec: Double, samplingRateHz: Int): FeatureExtractor.AxisRawData =
        suspendCancellableCoroutine { continuation ->
            if (accelSensor == null) {
                continuation.resumeWithException(
                    IllegalStateException("An accelerometer is required for vehicle classification")
                )
                return@suspendCancellableCoroutine
            }
            
            targetSamples = (durationSec * samplingRateHz).toInt()
            requestedSamplingRateHz = samplingRateHz
            accelX.clear()
            accelY.clear()
            accelZ.clear()
            gyroX.clear()
            gyroY.clear()
            gyroZ.clear()

            onComplete = { rawData ->
                continuation.resume(rawData)
            }

            continuation.invokeOnCancellation {
                stopSampling()
            }

            startSampling(samplingRateHz)
        }

    private fun startSampling(rateHz: Int) {
        if (isSampling) return
        isSampling = true

        val delayUs = 1000000 / rateHz // 20,000 microseconds (20ms) for 50Hz
        
        accelSensor?.let {
            sensorManager.registerListener(this, it, delayUs)
        }
        gyroSensor?.let {
            sensorManager.registerListener(this, it, delayUs)
        }
    }

    private fun stopSampling() {
        if (!isSampling) return
        isSampling = false
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (!isSampling) return

        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                accelX.add(event.values[0].toDouble())
                accelY.add(event.values[1].toDouble())
                accelZ.add(event.values[2].toDouble())
            }
            Sensor.TYPE_GYROSCOPE -> {
                gyroX.add(event.values[0].toDouble())
                gyroY.add(event.values[1].toDouble())
                gyroZ.add(event.values[2].toDouble())
            }
        }

        val reqAccel = if (accelSensor != null) targetSamples else 0
        val reqGyro = if (gyroSensor != null) targetSamples else 0

        // Check if we gathered enough samples on all available channels
        if (accelX.size >= reqAccel && gyroX.size >= reqGyro) {
            stopSampling()
            val rawData = FeatureExtractor.AxisRawData(
                accelX = accelX.take(targetSamples).toDoubleArray(),
                accelY = accelY.take(targetSamples).toDoubleArray(),
                accelZ = accelZ.take(targetSamples).toDoubleArray(),
                gyroX = gyroX.take(targetSamples).toDoubleArray(),
                gyroY = gyroY.take(targetSamples).toDoubleArray(),
                gyroZ = gyroZ.take(targetSamples).toDoubleArray(),
                samplingRateHz = requestedSamplingRateHz
            )
            onComplete?.invoke(rawData)
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}
