package io.github.foadsf.instruments.microscope

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import kotlin.math.sqrt

/**
 * Accelerometer and gyroscope samples, kept for the last [KEEP_NS], on their own thread. Sensor
 * timestamps share the elapsedRealtimeNanos clock, so windows are given in that clock ([now]).
 * Used by the calibration series to wait for a still phone and to record gravity per pose.
 */
class SensorRecorder(context: Context) : SensorEventListener {
    data class Sample(val type: Int, val tsNs: Long, val x: Float, val y: Float, val z: Float) {
        val norm: Double get() = sqrt((x * x + y * y + z * z).toDouble())
    }

    private val manager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val thread = HandlerThread("mic-sensors").apply { start() }
    private val samples = ArrayDeque<Sample>()

    val hasGyro: Boolean get() = manager.getDefaultSensor(Sensor.TYPE_GYROSCOPE) != null

    fun start() {
        val h = Handler(thread.looper)
        for (type in intArrayOf(Sensor.TYPE_ACCELEROMETER, Sensor.TYPE_GYROSCOPE)) {
            manager.getDefaultSensor(type)?.let { manager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME, h) }
        }
    }

    fun stop() {
        manager.unregisterListener(this)
        thread.quitSafely()
    }

    fun now(): Long = SystemClock.elapsedRealtimeNanos()

    override fun onSensorChanged(e: SensorEvent) {
        val s = Sample(e.sensor.type, e.timestamp, e.values[0], e.values[1], e.values[2])
        synchronized(samples) {
            samples.addLast(s)
            while (samples.isNotEmpty() && s.tsNs - samples.first().tsNs > KEEP_NS) samples.removeFirst()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    fun window(type: Int, fromNs: Long, toNs: Long): List<Sample> = synchronized(samples) {
        samples.filter { it.type == type && it.tsNs in fromNs..toNs }
    }

    /** Mean (x, y, z) over the window, or null without samples. */
    fun mean(type: Int, fromNs: Long, toNs: Long): DoubleArray? {
        val w = window(type, fromNs, toNs)
        if (w.isEmpty()) return null
        return doubleArrayOf(w.sumOf { it.x.toDouble() } / w.size, w.sumOf { it.y.toDouble() } / w.size,
            w.sumOf { it.z.toDouble() } / w.size)
    }

    /** Largest gyroscope rate (rad/s) in the window; +infinity without samples (cannot show stillness). */
    fun gyroMax(fromNs: Long, toNs: Long): Double =
        window(Sensor.TYPE_GYROSCOPE, fromNs, toNs).maxOfOrNull { it.norm } ?: Double.POSITIVE_INFINITY

    /** Blocks until the gyroscope stayed below [rateRadS] for [stillMs]; false after [timeoutMs]. */
    fun waitStill(rateRadS: Double, stillMs: Long, timeoutMs: Long): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            val t = now()
            val w = window(Sensor.TYPE_GYROSCOPE, t - stillMs * 1_000_000, t)
            if (w.size >= MIN_SAMPLES && w.first().tsNs - (t - stillMs * 1_000_000) < GAP_NS &&
                w.all { it.norm < rateRadS }) return true
            Thread.sleep(POLL_MS)
        }
        return false
    }

    /** Blocks until the gyroscope exceeds [rateRadS] (the phone is being moved); false after [timeoutMs]. */
    fun waitMotion(rateRadS: Double, timeoutMs: Long): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            val t = now()
            if (gyroMax(t - MOTION_WINDOW_NS, t).let { it.isFinite() && it > rateRadS }) return true
            Thread.sleep(POLL_MS)
        }
        return false
    }

    private companion object {
        const val KEEP_NS = 30_000_000_000L
        const val MIN_SAMPLES = 10
        const val GAP_NS = 200_000_000L
        const val POLL_MS = 50L
        const val MOTION_WINDOW_NS = 300_000_000L
    }
}
