package com.jarvis.edge.domain.features

import com.jarvis.edge.data.remote.FeatureSummary
import kotlin.math.*

object FeatureExtractor {

    data class AxisRawData(
        val accelX: DoubleArray,
        val accelY: DoubleArray,
        val accelZ: DoubleArray,
        val gyroX: DoubleArray,
        val gyroY: DoubleArray,
        val gyroZ: DoubleArray,
        val samplingRateHz: Int
    )

    fun extractFeatures(raw: AxisRawData): FeatureSummary {
        val n = raw.accelX.size
        if (n == 0) return FeatureSummary()

        // 1. Accel magnitudes
        val accelMag = DoubleArray(n)
        for (i in 0 until n) {
            accelMag[i] = sqrt(raw.accelX[i].pow(2) + raw.accelY[i].pow(2) + raw.accelZ[i].pow(2))
        }
        val accelMagnitudeMean = accelMag.average()
        val motionRms = computeRms(
            DoubleArray(n) { index -> accelMag[index] - accelMagnitudeMean }
        )
        val gyroRms = if (raw.gyroX.isNotEmpty()) {
            val gyroMagnitude = DoubleArray(raw.gyroX.size) { index ->
                sqrt(
                    raw.gyroX[index].pow(2) +
                        raw.gyroY[index].pow(2) +
                        raw.gyroZ[index].pow(2)
                )
            }
            val gyroMean = gyroMagnitude.average()
            computeRms(DoubleArray(gyroMagnitude.size) { index -> gyroMagnitude[index] - gyroMean })
        } else {
            0.0
        }

        // 2. Compute Z-axis statistics (which represents gravity + engine thumper vibration)
        val zMean = raw.accelZ.average()
        val zRms = computeRms(raw.accelZ)
        
        // Zero-crossing rate of Z-axis
        val zCentered = raw.accelZ.map { it - zMean }.toDoubleArray()
        val zcr = computeZeroCrossingRate(zCentered)

        // 3. FFT on Z-axis acceleration to detect single-cylinder firing peak
        // Pad size to next power of 2 (256)
        val fftSize = 256
        val padded = DoubleArray(fftSize)
        System.arraycopy(raw.accelZ, 0, padded, 0, min(n, fftSize))
        // Subtract DC component (mean)
        val meanVal = padded.average()
        for (i in 0 until fftSize) {
            padded[i] -= meanVal
        }

        // Apply Hanning window
        for (i in 0 until fftSize) {
            val window = 0.5 * (1 - cos(2 * PI * i / (fftSize - 1)))
            padded[i] *= window
        }

        val fftResult = fftRadix2(padded)
        val fftMag = DoubleArray(fftSize / 2)
        for (i in 0 until fftSize / 2) {
            fftMag[i] = Complex.magnitude(fftResult[i]) / fftSize
        }

        // Dominant frequency index (skip index 0 / DC)
        var maxIdx = 1
        var maxVal = 0.0
        for (i in 1 until fftSize / 2) {
            if (fftMag[i] > maxVal) {
                maxVal = fftMag[i]
                maxIdx = i
            }
        }

        val df = maxIdx.toDouble() * raw.samplingRateHz / fftSize
        val energy = fftMag.map { it.pow(2) }.sum()

        // Harmonic ratio: magnitude of 2nd harmonic / magnitude of dominant frequency
        var harmonicRatio = 0.0
        val harmonicIdx = maxIdx * 2
        if (harmonicIdx < fftSize / 2 && maxVal > 1e-12) {
            harmonicRatio = fftMag[harmonicIdx] / maxVal
        }

        return FeatureSummary(
            dominantFreqHz = df,
            spectralEnergy = energy,
            zRms = zRms,
            harmonicRatio = harmonicRatio,
            accelMagnitudeMean = accelMagnitudeMean,
            motionRms = motionRms,
            gyroRms = gyroRms
        )
    }

    private fun computeRms(data: DoubleArray): Double {
        var sum = 0.0
        for (v in data) {
            sum += v.pow(2)
        }
        return sqrt(sum / data.size)
    }

    private fun computeZeroCrossingRate(centered: DoubleArray): Double {
        var crossings = 0
        for (i in 0 until centered.size - 1) {
            if (centered[i] * centered[i + 1] < 0) {
                crossings++
            }
        }
        return crossings.toDouble() / centered.size
    }

    // ── Pure Kotlin FFT (Radix-2 Cooley-Tukey) ───────────────────────────────

    private class Complex(val real: Double, val imag: Double) {
        operator fun plus(other: Complex) = Complex(real + other.real, imag + other.imag)
        operator fun minus(other: Complex) = Complex(real - other.real, imag - other.imag)
        operator fun times(other: Complex) = Complex(
            real * other.real - imag * other.imag,
            real * other.imag + imag * other.real
        )
        companion object {
            fun magnitude(c: Complex) = sqrt(c.real.pow(2) + c.imag.pow(2))
        }
    }

    private fun fftRadix2(input: DoubleArray): Array<Complex> {
        val n = input.size
        val out = Array(n) { i -> Complex(input[i], 0.0) }
        
        // Bit reversal
        var j = 0
        for (i in 0 until n) {
            if (i < j) {
                val temp = out[i]
                out[i] = out[j]
                out[j] = temp
            }
            var m = n shr 1
            while (m in 1..j) {
                j = j xor m
                m = m shr 1
            }
            j = j or m
        }

        // Cooley-Tukey decimation-in-time
        var len = 2
        while (len <= n) {
            val angle = -2 * PI / len
            val wlen = Complex(cos(angle), sin(angle))
            for (i in 0 until n step len) {
                var w = Complex(1.0, 0.0)
                for (k in 0 until len / 2) {
                    val u = out[i + k]
                    val t = w * out[i + k + len / 2]
                    out[i + k] = u + t
                    out[i + k + len / 2] = u - t
                    w *= wlen
                }
            }
            len = len shl 1
        }
        return out
    }
}
