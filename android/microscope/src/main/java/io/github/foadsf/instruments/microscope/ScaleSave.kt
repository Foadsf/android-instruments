package io.github.foadsf.instruments.microscope

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import io.github.foadsf.instruments.microscope.core.Optics
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Save as a hand-held burst for fusion (microscope-scale.md): [FRAMES] consecutive raw I420 frames,
 * the raw gyroscope and accelerometer at their fastest rate in `imu.csv` (same clock as the frame
 * stamps), and `scale.json` with each frame's focus, fx and µm per pixel, plus the gyroscope maximum
 * over each frame's exposure and readout. Blocks: call from the camera worker thread.
 */
class ScaleSave(private val context: Context, private val station: Station) {
    fun save(dir: File, frames: Int = FRAMES): JSONObject {
        check(dir.isDirectory || dir.mkdirs()) { "cannot create $dir" }
        val sensors = SensorRecorder(context)
        sensors.start(fastest = true)
        sensors.startLog(File(dir, "imu.csv"))
        try {
            Thread.sleep(IMU_LEAD_MS)
            val burst = station.burst(dir, frames)
            Thread.sleep(IMU_TAIL_MS)
            val scale = scale(burst, sensors)
            writeAtomic(File(dir, "scale.json"), scale)
            return JSONObject().put("dir", dir.name).put("frames", burst.getInt("frames"))
                .put("complete", burst.getBoolean("complete")).put("scale", scale)
        } finally {
            sensors.stop()
        }
    }

    private fun scale(burst: JSONObject, sensors: SensorRecorder): JSONObject {
        val cam = burst.optString("camera_id")
        val w = burst.getInt("width")
        val lens = if (cam == "0") Optics.camera0(w) else null
        val ts = burst.getJSONArray("timestamps_ns")
        val per = JSONArray()
        for (i in 0 until ts.length()) {
            val t = ts.getLong(i)
            val d = burst.getJSONArray("focus_distance_diopters").optDouble(i).takeIf { it.isFinite() }
            val exp = burst.getJSONArray("exposure_ns").optLong(i, 0L)
            val skew = burst.getJSONArray("rolling_shutter_skew_ns").optLong(i, 0L)
            val g = sensors.gyroMax(t - PAD_NS, t + exp + skew + PAD_NS)
            val dt = if (lens != null) Optics.trueFocus(d) else null
            per.put(JSONObject().put("ts_ns", t).put("focus_diopters", d ?: JSONObject.NULL)
                .put("focus_true_diopters", dt ?: JSONObject.NULL)
                .put("fx_px", lens?.let { Optics.fxPx(it, dt) } ?: JSONObject.NULL)
                .put("um_per_px", lens?.let { Optics.umPerPx(it, dt) } ?: JSONObject.NULL)
                .put("gyro_max_rad_s", if (g.isFinite()) g else JSONObject.NULL))
        }
        return JSONObject().put("camera_id", cam).put("width", w).put("height", burst.getInt("height"))
            .put("model", Optics.MODEL).put("calibrated", lens != null)
            .put("reason", if (lens == null) "camera $cam has no calibration; only camera 0 does" else JSONObject.NULL)
            .put("calibration_runs", JSONArray(Optics.CAM0_RUNS))
            .put("fx0_px", Optics.CAM0_FX0).put("d0_diopters", Optics.CAM0_D0)
            .put("focus_offset_diopters", Optics.CAM0_FOCUS_OFFSET_D).put("focus_offset_run", Optics.CAM0_OFFSET_RUN)
            .put("focal_mm", lens?.focalMm ?: JSONObject.NULL).put("pitch_mm", lens?.pitchMm ?: JSONObject.NULL)
            .put("frames", per)
    }

    /**
     * The adb evidence run: camera 0, OIS off, [bursts] Saves [gapMs] apart. A long beep means
     * "move to the next distance", a short one "burst starts". Writes `microscope_scale_<run>.json`.
     */
    fun run(runId: String, bursts: Int, gapMs: Long, outDir: File, status: (String) -> Unit): File {
        station.oisOff = true
        station.focusDiopters = null
        station.open("0")
        station.stream(WARM_MS)
        val root = File(outDir, "captures/${runId}_scale")
        val tone = runCatching { ToneGenerator(AudioManager.STREAM_NOTIFICATION, TONE_VOLUME) }.getOrNull()
        val out = JSONArray()
        try {
            for (i in 0 until bursts) {
                status("Burst ${i + 1}/$bursts: move to the next distance")
                tone?.startTone(ToneGenerator.TONE_PROP_BEEP2, LONG_MS)
                Thread.sleep(gapMs)
                waitFocused(AF_WAIT_MS)
                tone?.startTone(ToneGenerator.TONE_PROP_BEEP, SHORT_MS)
                out.put(save(File(root, "b%02d".format(i))))
            }
            tone?.startTone(ToneGenerator.TONE_PROP_BEEP2, LONG_MS)
        } finally {
            tone?.release()
            station.close()
        }
        val report = JSONObject().put("run_id", runId).put("unit", "microscope_scale").put("camera_id", "0")
            .put("ois", "off").put("af", "camera default (continuous)").put("folder", root.name).put("bursts", out)
        return File(outDir, "microscope_scale_$runId.json").also { writeAtomic(it, report) }
    }

    /** Waits until continuous AF reports focused (PASSIVE_FOCUSED or FOCUSED_LOCKED), at most [ms]. */
    private fun waitFocused(ms: Long) {
        val end = System.currentTimeMillis() + ms
        while (System.currentTimeMillis() < end && station.lastMeta?.afState !in FOCUSED) Thread.sleep(POLL_MS)
    }

    private fun writeAtomic(file: File, json: JSONObject) {
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(json.toString(2))
        check(tmp.renameTo(file)) { "cannot write $file" }
    }

    companion object {
        const val FRAMES = 16
        /** CONTROL_AF_STATE_PASSIVE_FOCUSED (2) and FOCUSED_LOCKED (4). */
        val FOCUSED = setOf(2, 4)
        private const val AF_WAIT_MS = 2000L
        private const val POLL_MS = 50L
        private const val IMU_LEAD_MS = 300L
        private const val IMU_TAIL_MS = 100L
        private const val PAD_NS = 5_000_000L
        private const val WARM_MS = 2000L
        private const val TONE_VOLUME = 80
        private const val LONG_MS = 400
        private const val SHORT_MS = 120
    }
}
