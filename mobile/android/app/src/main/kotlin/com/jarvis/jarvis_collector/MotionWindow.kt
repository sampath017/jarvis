package com.jarvis.jarvis_collector

import kotlin.math.sqrt

/** Independent, provisional phone-motion evidence; never a trained probability. */
data class MotionResult(val candidate: String, val rms: Double, val samples: Int,
    val spanMs: Long, val maxGapMs: Long, val steps: Int, val usable: Boolean,
    val gyroRms: Double? = null)

class MotionWindow {
    private var first = 0L
    private var last = 0L
    private var maxGap = 0L
    private var n = 0
    private var sum = 0.0
    private var squares = 0.0
    private var steps = 0
    private var gyroSquares = 0.0
    private var gyroSamples = 0

    fun gyro(x: Double, y: Double, z: Double) {
        if (x.isFinite() && y.isFinite() && z.isFinite()) { gyroSquares += x*x+y*y+z*z; gyroSamples++ }
    }

    fun sample(atMs: Long, x: Double, y: Double, z: Double) {
        if (!x.isFinite() || !y.isFinite() || !z.isFinite() || (n > 0 && atMs <= last)) return
        val magnitude = sqrt(x*x + y*y + z*z)
        if (n == 0) first = atMs else maxGap = maxOf(maxGap, atMs - last)
        last = atMs; n++; sum += magnitude; squares += magnitude*magnitude
    }

    fun step() { steps++ }

    fun result(nowMs: Long, speedMps: Double? = null): MotionResult {
        val span = if (n == 0) 0 else last - first
        val rms = if (n == 0) 0.0 else sqrt(maxOf(0.0, squares/n - (sum/n)*(sum/n)))
        // Silence or batched old data is unknown, never proof of stillness.
        val usable = n >= 40 && span >= 8_000 && maxGap <= 2_000 && nowMs - last in 0..2_000
        val candidate = when {
            !usable -> "UNKNOWN"
            steps >= 3 -> "ON_FOOT"
            speedMps != null && speedMps.isFinite() && speedMps >= 5.0 -> "IN_VEHICLE"
            rms < 0.12 && (speedMps == null || speedMps < 0.5) -> "STILL"
            else -> "UNKNOWN"
        }
        return MotionResult(candidate, rms, n, span, maxGap, steps, usable,
            if (gyroSamples == 0) null else sqrt(gyroSquares/gyroSamples))
    }
}
