package com.jarvis.jarvis_collector

import android.content.Context
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer
import java.nio.LongBuffer

/** Silero VAD v5.1: speech probability, independent of absolute microphone volume. */
class SpeechDetector(c: Context): AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private val session = OrtSession.SessionOptions().use { options ->
        options.setIntraOpNumThreads(1)
        options.setInterOpNumThreads(1)
        env.createSession(c.assets.open("vad/silero_vad.onnx").use { it.readBytes() }, options)
    }
    private var state = FloatArray(256)
    private var context = FloatArray(64)
    fun reset() { state.fill(0f); context.fill(0f) }
    fun probability(samples: ShortArray): Float {
        require(samples.size == 512)
        val input = FloatArray(576)
        context.copyInto(input)
        for(i in samples.indices) input[i+64]=samples[i]/32768f
        OnnxTensor.createTensor(env, FloatBuffer.wrap(input), longArrayOf(1,576)).use { audio ->
            OnnxTensor.createTensor(env, FloatBuffer.wrap(state), longArrayOf(2,1,128)).use { memory ->
                OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(16000)), longArrayOf()).use { rate ->
                    session.run(mapOf("input" to audio, "state" to memory, "sr" to rate)).use { result ->
                        val next = (result[1] as OnnxTensor).floatBuffer
                        next.get(state)
                        context = input.copyOfRange(512,576)
                        return (result[0] as OnnxTensor).floatBuffer.get(0)
                    }
                }
            }
        }
    }
    override fun close() { session.close() }
}
