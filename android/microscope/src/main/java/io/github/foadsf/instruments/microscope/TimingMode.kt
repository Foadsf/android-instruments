package io.github.foadsf.instruments.microscope

import android.content.Context
import android.os.Build
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import io.github.foadsf.instruments.microscope.core.Sharpness
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import kotlin.math.abs
import kotlin.random.Random

/**
 * When does a frame's exposure happen relative to its timestamp? (camera-calibration.md, frame
 * timing amendment). Each camera streams for [Plan.seconds] while the vibration motor gives short
 * pulses at random intervals. The gyroscope sees each pulse at once (imu.csv); a frame whose
 * exposure overlaps a pulse is blurred and differs from its neighbour. Per frame this records the
 * timestamp, the centre-half sharpness and the mean difference from the previous frame; the host
 * (tools/calib/frame_timing.py) finds the window [ts + offset, ts + offset + width] that best
 * explains them. Camera 0, whose window is known from its capture result, is the control.
 */
class TimingMode(private val context: Context, private val station: Station, private val sensors: SensorRecorder,
                 private val outDir: File, private val onProgress: (String) -> Unit) {
    /** [maxExposureNs]: the sweep's exposure cap, so the control camera is timed as it is used. */
    data class Plan(val runId: String, val cameraIds: List<String>, val seconds: Int = 12, val warmMs: Long = 1500,
                    val maxExposureNs: Long? = null)

    private class FrameRow(val ts: Long, val sharpness: Double, val diff: Double)

    fun execute(plan: Plan): File {
        val root = File(outDir, "captures/${plan.runId}_timing").apply { mkdirs() }
        val vib = context.getSystemService(Vibrator::class.java)
        val cams = JSONObject()
        sensors.start(fastest = true)
        sensors.startLog(File(root, "imu.csv"))
        try {
            for (id in plan.cameraIds) cams.put(id, timeCamera(plan, id, vib))
        } finally {
            station.close()
            sensors.stop()
        }
        val report = JSONObject().put("unit", "frame_timing").put("run_id", plan.runId).put("model", Build.MODEL)
            .put("imu_log", "imu.csv").put("cameras", cams)
        File(root, "timing.json").writeText(report.toString(2))
        return File(outDir, "microscope_timing_${plan.runId}.json").also { it.writeText(report.toString(2)) }
    }

    private fun timeCamera(plan: Plan, id: String, vib: Vibrator?): JSONObject {
        val size = station.open(id)
        station.stream(plan.warmMs)
        val exposure = plan.maxExposureNs?.let { station.capExposure(it).also { station.stream(EXPOSURE_SETTLE_MS) } }
        val rows = ArrayList<FrameRow>()
        val roi = Sharpness.centreHalf(size.w, size.h)
        var prev: ByteArray? = null
        station.tap = { y, w, _, ts ->
            val small = subsample(y, w, roi.left, roi.top, roi.right, roi.bottom)
            val d = prev?.let { p -> meanAbsDiff(p, small) } ?: Double.NaN
            prev = small
            synchronized(rows) { rows.add(FrameRow(ts, Sharpness.meanSquaredLaplacian(y, w, roi), d)) }
        }
        val pulses = JSONArray()
        val rnd = Random(id.hashCode())
        val end = SystemClock.elapsedRealtime() + plan.seconds * 1000L
        while (SystemClock.elapsedRealtime() < end) {
            onProgress("Timing camera $id: hold the phone at something with detail; it will buzz")
            Thread.sleep(rnd.nextLong(PULSE_GAP_MS.first, PULSE_GAP_MS.last))
            pulses.put(sensors.now())
            vib?.vibrate(VibrationEffect.createOneShot(PULSE_MS, VibrationEffect.DEFAULT_AMPLITUDE))
        }
        Thread.sleep(500)
        station.tap = null
        val frames = JSONArray()
        synchronized(rows) {
            for (r in rows) {
                val m = station.meta(r.ts)
                frames.put(JSONObject().put("ts_ns", r.ts).put("sharpness", r.sharpness)
                    .put("diff", if (r.diff.isNaN()) JSONObject.NULL else r.diff)
                    .put("exposure_ns", m?.exposureNs ?: JSONObject.NULL).put("skew_ns", m?.skewNs ?: JSONObject.NULL))
            }
        }
        station.close()
        return JSONObject().put("vibrator", vib?.hasVibrator() ?: false).put("pulse_ms", PULSE_MS)
            .put("pulse_command_ns", pulses).put("exposure", exposure ?: JSONObject.NULL).put("frames", frames)
    }

    /** Every 8th pixel of the region, for a cheap frame-to-frame difference. */
    private fun subsample(y: ByteArray, stride: Int, l: Int, t: Int, r: Int, b: Int): ByteArray {
        val out = ByteArray(((r - l) / STEP) * ((b - t) / STEP))
        var k = 0
        for (row in t until b - STEP + 1 step STEP) for (col in l until r - STEP + 1 step STEP) if (k < out.size) out[k++] = y[row * stride + col]
        return out
    }

    private fun meanAbsDiff(a: ByteArray, b: ByteArray): Double {
        var s = 0L
        for (i in a.indices) s += abs((a[i].toInt() and 0xff) - (b[i].toInt() and 0xff))
        return s.toDouble() / a.size
    }

    private companion object {
        const val PULSE_MS = 60L
        val PULSE_GAP_MS = 350L..800L
        const val STEP = 8
        const val EXPOSURE_SETTLE_MS = 600L
    }
}
