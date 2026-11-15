package io.github.foadsf.instruments.microscope

import android.hardware.Sensor
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * The calibration capture series (docs/units/camera-calibration.md), started over adb by
 * tools/microscope/run_live.py --series N. Per pose: wait until the gyroscope shows the phone
 * still, capture a short burst from each camera in turn, record the accelerometer and gyroscope
 * over the capture, beep, then wait for the phone to be moved before the next pose. Writes
 * captures/<runId>_series/series.json (after every pose) and microscope_series_<runId>.json.
 */
class SeriesMode(private val station: Station, private val sensors: SensorRecorder, private val outDir: File) {
    data class Plan(val runId: String, val cameraIds: List<String>, val poses: Int, val stillMs: Long,
                    val burst: Int = 4, val warmMs: Long = 800, val focusDiopters: Float? = null, val oisOff: Boolean = true)

    fun execute(plan: Plan): File {
        station.oisOff = plan.oisOff
        station.focusDiopters = plan.focusDiopters
        val root = File(outDir, "captures/${plan.runId}_series").apply { mkdirs() }
        val poses = JSONArray()
        var end = "completed"
        val tone = runCatching { ToneGenerator(AudioManager.STREAM_NOTIFICATION, TONE_VOLUME) }.getOrNull()
        sensors.start()
        try {
            aim(plan)
            for (i in 0 until plan.poses) {
                if (i > 0 && !sensors.waitMotion(MOVE_RAD_S, MOVE_TIMEOUT_MS)) { end = "no movement after pose ${i - 1}"; break }
                if (!sensors.waitStill(STILL_RAD_S, plan.stillMs, STILL_TIMEOUT_MS)) { end = "never still before pose $i"; break }
                poses.put(capturePose(plan, i, root))
                tone?.startTone(ToneGenerator.TONE_PROP_BEEP2, TONE_MS)
                writeAtomic(File(root, "series.json"), summary(plan, poses, "in progress"))
                aim(plan)
            }
        } finally {
            station.close()
            sensors.stop()
            tone?.release()
        }
        val report = summary(plan, poses, end)
        writeAtomic(File(root, "series.json"), report)
        return File(outDir, "microscope_series_${plan.runId}.json").also { writeAtomic(it, report) }
    }

    /** Between poses the narrowest camera (the last listed, camera 2) streams to the screen so Foad
     *  can aim: if the board fits its view, it fits the wider camera's. Nothing is recorded. */
    private fun aim(plan: Plan) {
        plan.cameraIds.lastOrNull()?.let { id -> runCatching { station.open(id) } }
    }

    private fun capturePose(plan: Plan, index: Int, root: File): JSONObject {
        val dir = "pose_%02d".format(index)
        val bursts = JSONObject()
        val cams = JSONObject()
        val t0 = sensors.now()
        for (id in plan.cameraIds) {
            val rel = "$dir/cam$id"
            try {
                station.open(id)
                station.stream(plan.warmMs)
                val b = station.burst(File(root, rel), plan.burst)
                bursts.put(id, rel)
                cams.put(id, JSONObject().put("frames", b.optInt("frames")).put("focus_diopters", first(b, "focus_distance_diopters"))
                    .put("af_mode", first(b, "af_mode")).put("exposure_ns", first(b, "exposure_ns")).put("ois_mode", first(b, "ois_mode")))
            } catch (e: Exception) {
                cams.put(id, JSONObject().put("error", e.toString()))
            } finally {
                station.close()
            }
        }
        val t1 = sensors.now()
        val gyroMax = sensors.gyroMax(t0, t1)
        return JSONObject().apply {
            put("index", index)
            put("dir", dir)
            put("status", if (gyroMax.isFinite() && gyroMax <= MOVED_RAD_S) "ok" else "moved")
            put("gyro_max_rad_s", if (gyroMax.isFinite()) gyroMax else JSONObject.NULL)
            put("accel_mean", vec(sensors.mean(Sensor.TYPE_ACCELEROMETER, t0, t1)))
            put("gyro_mean", vec(sensors.mean(Sensor.TYPE_GYROSCOPE, t0, t1)))
            put("accel_samples", sensors.window(Sensor.TYPE_ACCELEROMETER, t0, t1).size)
            put("capture_s", (t1 - t0) / 1e9)
            put("bursts", bursts)
            put("cameras", cams)
        }
    }

    private fun summary(plan: Plan, poses: JSONArray, end: String) = JSONObject().apply {
        put("unit", "camera_calibration_series")
        put("run_id", plan.runId)
        put("model", Build.MODEL)
        put("cameras", JSONArray(plan.cameraIds))
        put("poses_requested", plan.poses)
        put("still_ms", plan.stillMs)
        put("still_rad_s", STILL_RAD_S)
        put("moved_rad_s", MOVED_RAD_S)
        put("focus_diopters", plan.focusDiopters ?: JSONObject.NULL)
        put("ois", if (plan.oisOff) "off" else "camera default")
        put("gyroscope", sensors.hasGyro)
        put("end", end)
        put("poses", poses)
    }

    private fun first(b: JSONObject, key: String): Any = b.optJSONArray(key)?.opt(0) ?: JSONObject.NULL

    private fun vec(v: DoubleArray?): Any = v?.let { JSONArray(it.toList()) } ?: JSONObject.NULL

    private fun writeAtomic(file: File, json: JSONObject) {
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(json.toString(2))
        check(tmp.renameTo(file)) { "cannot write $file" }
    }

    private companion object {
        const val STILL_RAD_S = 0.01
        const val MOVED_RAD_S = 0.02
        const val MOVE_RAD_S = 0.15
        const val STILL_TIMEOUT_MS = 180_000L // run 124500-55c8 gave up after 60 s while Foad read the instructions
        const val MOVE_TIMEOUT_MS = 180_000L
        const val TONE_VOLUME = 100
        const val TONE_MS = 300
    }
}
