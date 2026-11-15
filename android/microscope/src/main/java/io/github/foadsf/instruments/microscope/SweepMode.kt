package io.github.foadsf.instruments.microscope

import android.hardware.Sensor
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.SystemClock
import io.github.foadsf.instruments.microscope.core.FrameGate
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.ArrayBlockingQueue

/**
 * Hand-held calibration capture (camera-calibration.md, hand-held amendment), started over adb by
 * tools/microscope/run_live.py --sweep N. Nothing waits for a still phone: each camera in turn
 * streams to the screen while Foad moves the phone slowly around the target, and a frame is kept
 * when the gyroscope was calm over that frame's exposure and readout ([FrameGate]). A short beep
 * marks each kept frame, a long one the end of a camera. Writes captures/<runId>_series in the
 * series layout calibrate.py reads (one "pose" per kept frame, one camera each), the raw IMU log
 * imu.csv, and microscope_series_<runId>.json.
 */
class SweepMode(private val station: Station, private val sensors: SensorRecorder, private val outDir: File,
                private val onProgress: (String) -> Unit) {
    /** [gates]: gyro limit (rad/s) per camera id; camera 2's long focal length needs the stricter one. */
    data class Plan(val runId: String, val cameraIds: List<String>, val frames: Int, val gates: Map<String, Double>,
                    val minGapMs: Long = 600, val maxMs: Long = 300_000, val warmMs: Long = 1500,
                    val focusDiopters: Float? = null, val oisOff: Boolean = true, val maxExposureNs: Long? = null)

    /** [lagNs]: arrival time minus sensor timestamp, both elapsedRealtimeNanos if the camera's
     *  timestamp source is REALTIME as reported; recorded to check that claim on the bridge. */
    private class Pending(val buf: ByteArray, val ts: Long, val lagNs: Long)

    private val poses = JSONArray()
    private val perCamera = JSONObject()
    private var tone: ToneGenerator? = null
    @Volatile private var lastKept: Long? = null
    @Volatile private var lastCandidate = 0L

    fun execute(plan: Plan): File {
        station.oisOff = plan.oisOff
        station.focusDiopters = plan.focusDiopters
        val root = File(outDir, "captures/${plan.runId}_series").apply { mkdirs() }
        tone = runCatching { ToneGenerator(AudioManager.STREAM_NOTIFICATION, TONE_VOLUME) }.getOrNull()
        sensors.start(fastest = true)
        sensors.startLog(File(root, "imu.csv"))
        var end = "completed"
        try {
            for (id in plan.cameraIds) {
                val gate = FrameGate(plan.gates.getValue(id), plan.minGapMs * MS, PAD_NS, MIN_SAMPLES)
                val (got, stats) = sweepCamera(plan, gate, id, root)
                perCamera.put(id, stats.put("gate_rad_s", gate.rateRadS))
                writeAtomic(File(root, "series.json"), summary(plan, "in progress"))
                if (got < plan.frames) end = "camera $id: $got of ${plan.frames} frames in ${plan.maxMs / 1000} s"
            }
        } finally {
            station.close()
            sensors.stop()
            tone?.release()
        }
        val report = summary(plan, end)
        writeAtomic(File(root, "series.json"), report)
        return File(outDir, "microscope_series_${plan.runId}.json").also { writeAtomic(it, report) }
    }

    private fun sweepCamera(plan: Plan, gate: FrameGate, id: String, root: File): Pair<Int, JSONObject> {
        val stats = JSONObject()
        val size = station.open(id)
        station.stream(plan.warmMs)
        plan.maxExposureNs?.let { stats.put("exposure", station.capExposure(it)); station.stream(EXPOSURE_SETTLE_MS) }
        val free = ArrayBlockingQueue<ByteArray>(SLOTS).apply { repeat(SLOTS) { offer(ByteArray(size.w * size.h)) } }
        val pending = ArrayBlockingQueue<Pending>(SLOTS)
        lastKept = null
        station.tap = { i420, w, h, ts -> offerCandidate(i420, w * h, ts, gate, free, pending) }
        beep(ToneGenerator.TONE_PROP_BEEP2, LONG_MS)
        val rejected = mutableMapOf<String, Int>()
        val rates = JSONArray()
        val lags = ArrayList<Long>()
        var kept = 0
        val t0 = SystemClock.elapsedRealtime()
        while (kept < plan.frames && SystemClock.elapsedRealtime() - t0 < plan.maxMs) {
            onProgress("Camera $id: $kept of ${plan.frames} frames. Move slowly around the screen.")
            val p = pending.peek()
            if (p == null || sensors.now() < p.ts + DECIDE_AFTER_NS) { Thread.sleep(POLL_MS); continue }
            pending.poll()
            lags.add(p.lagNs)
            val m = station.meta(p.ts)
            val (start, exp, skew) = timing(p.ts, m)
            val w = gate.window(start, exp, skew)
            val d = gate.decide(start, exp, skew, sensors.gyroRates(w.first, w.last), lastKept)
            if (d.maxRate.isFinite()) rates.put(Math.round(d.maxRate * 1e4) / 1e4)
            if (d.keep) {
                poses.put(keep(id, p, size.w, size.h, root, kept, m, d, w))
                lastKept = p.ts
                kept++
                beep(ToneGenerator.TONE_PROP_BEEP, SHORT_MS)
            } else {
                val key = d.reason.substringBefore(' ')
                rejected[key] = (rejected[key] ?: 0) + 1
            }
            free.offer(p.buf)
        }
        station.close()
        beep(ToneGenerator.TONE_PROP_BEEP2, LONG_MS)
        return kept to stats.put("kept", kept).put("seconds", (SystemClock.elapsedRealtime() - t0) / 1000.0)
            .put("rejected", JSONObject(rejected as Map<*, *>)).put("candidate_gyro_max_rad_s", rates)
            .put("arrival_lag_ms", JSONObject().put("median", lags.sorted().getOrNull(lags.size / 2)?.let { it / 1e6 } ?: JSONObject.NULL)
                .put("min", lags.minOrNull()?.let { it / 1e6 } ?: JSONObject.NULL)
                .put("max", lags.maxOrNull()?.let { it / 1e6 } ?: JSONObject.NULL))
    }

    /**
     * When the sensor saw the frame: (start, exposure, readout). With exposure and skew in the
     * capture result (camera 0), the timestamp is the first row's exposure start (Camera2). The
     * camera 2 bridge reports neither, and stamps the frame when HAL1 delivers it (bridge_tele.c,
     * CLOCK_BOOTTIME at the data callback), after exposure, readout and the ISP: so the window is
     * the BRIDGE_BEFORE_NS before the stamp (the HAL1 delivery delay itself is not measured).
     */
    private fun timing(ts: Long, m: FrameMeta?): Triple<Long, Long, Long> {
        val exp = m?.exposureNs
        val skew = m?.skewNs
        return if (exp != null && skew != null) Triple(ts, exp, skew) else Triple(ts - BRIDGE_BEFORE_NS, 0L, BRIDGE_BEFORE_NS)
    }

    /** On the image thread: copy the luma of a candidate frame into a free slot, never more. */
    private fun offerCandidate(i420: ByteArray, n: Int, ts: Long, gate: FrameGate, free: ArrayBlockingQueue<ByteArray>,
                               pending: ArrayBlockingQueue<Pending>) {
        val last = lastKept
        if (ts - lastCandidate < CANDIDATE_NS || (last != null && ts - last < gate.minGapNs)) return
        val buf = free.poll() ?: return
        System.arraycopy(i420, 0, buf, 0, n)
        if (pending.offer(Pending(buf, ts, sensors.now() - ts))) lastCandidate = ts else free.offer(buf)
    }

    private fun keep(id: String, p: Pending, w: Int, h: Int, root: File, n: Int, m: FrameMeta?, d: FrameGate.Decision,
                     win: LongRange): JSONObject {
        val index = poses.length()
        val rel = "cam$id/v%03d".format(n)
        val dir = File(root, rel).apply { mkdirs() }
        File(dir, "frame_00.yuv").writeBytes(p.buf)  // luma plane only: calibrate.py reads the first w x h bytes
        File(dir, "burst.json").writeText(JSONObject().put("format", "Y").put("width", w).put("height", h)
            .put("frames", 1).put("timestamps_ns", JSONArray(listOf(p.ts))).toString(2))
        val cam = JSONObject().put("focus_diopters", m?.focusDiopters ?: JSONObject.NULL)
            .put("af_mode", m?.afMode ?: JSONObject.NULL).put("exposure_ns", m?.exposureNs ?: JSONObject.NULL)
            .put("iso", m?.iso ?: JSONObject.NULL).put("rolling_shutter_skew_ns", m?.skewNs ?: JSONObject.NULL)
            .put("ois_mode", m?.oisMode ?: JSONObject.NULL)
            .put("timing", if (m?.exposureNs != null && m.skewNs != null) "capture result: exposure and skew after the stamp"
                else "bridge: ${BRIDGE_BEFORE_NS / MS} ms before the delivery stamp")
        return JSONObject().apply {
            put("index", index)
            put("camera", id)
            put("dir", rel)
            put("status", "ok")
            put("ts_ns", p.ts)
            put("gate_window_ns", JSONArray(listOf(win.first, win.last)))
            put("gyro_max_rad_s", d.maxRate)
            put("gyro_samples", d.samples)
            put("gyro_mean", vec(sensors.mean(Sensor.TYPE_GYROSCOPE, win.first, win.last)))
            put("accel_mean", vec(sensors.mean(Sensor.TYPE_ACCELEROMETER, win.first - ACCEL_PAD_NS, win.last + ACCEL_PAD_NS)))
            put("bursts", JSONObject().put(id, rel))
            put("cameras", JSONObject().put(id, cam))
        }
    }

    private fun summary(plan: Plan, end: String) = JSONObject().apply {
        put("unit", "camera_calibration_series")
        put("capture", "hand-held sweep")
        put("run_id", plan.runId)
        put("model", Build.MODEL)
        put("cameras", JSONArray(plan.cameraIds))
        put("frames_requested", plan.frames)
        put("gate_rad_s", JSONObject(plan.gates as Map<*, *>))
        put("gate_pad_ns", PAD_NS)
        put("min_gap_ms", plan.minGapMs)
        put("max_exposure_ns", plan.maxExposureNs ?: JSONObject.NULL)
        put("focus_diopters", plan.focusDiopters ?: JSONObject.NULL)
        put("ois", if (plan.oisOff) "off" else "camera default")
        put("gyroscope", sensors.hasGyro)
        put("imu_log", "imu.csv")
        put("per_camera", perCamera)
        put("end", end)
        put("poses", poses)
    }

    private fun beep(kind: Int, ms: Int) { tone?.startTone(kind, ms) }

    private fun vec(v: DoubleArray?): Any = v?.let { JSONArray(it.toList()) } ?: JSONObject.NULL

    private fun writeAtomic(file: File, json: JSONObject) {
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(json.toString(2))
        check(tmp.renameTo(file)) { "cannot write $file" }
    }

    private companion object {
        const val MS = 1_000_000L
        const val PAD_NS = 5 * MS
        const val MIN_SAMPLES = 4
        const val SLOTS = 8  // every frame is a candidate: ~5 in flight while the gyro catches up
        const val CANDIDATE_NS = 20 * MS
        const val DECIDE_AFTER_NS = 150 * MS  // exposure + readout + sensor delivery, all well inside
        const val BRIDGE_BEFORE_NS = 150 * MS  // camera 2: exposure, readout and HAL1 delay before its stamp
        const val ACCEL_PAD_NS = 50 * MS
        const val EXPOSURE_SETTLE_MS = 600L
        const val POLL_MS = 5L
        const val TONE_VOLUME = 100
        const val SHORT_MS = 80
        const val LONG_MS = 400
    }
}
