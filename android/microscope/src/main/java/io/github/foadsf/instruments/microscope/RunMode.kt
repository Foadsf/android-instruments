package io.github.foadsf.instruments.microscope

import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * The evidence run, started over adb by tools/microscope/run_live.py: per camera, open, stream
 * for a while, record a burst, close. Writes `microscope_live_<runId>.json` into [outDir]; bursts
 * go to `captures/<runId>_cam<id>/`. Errors are recorded per camera, never swallowed.
 */
class RunMode(private val station: Station, private val outDir: File) {
    data class Plan(val runId: String, val cameraIds: List<String>, val streamMs: Long, val burst: Int)

    fun execute(plan: Plan): File {
        val (listed, rear) = station.cameras()
        val cameras = JSONArray()
        for (id in plan.cameraIds) cameras.put(runOne(plan, id))
        val report = JSONObject().apply {
            put("unit", "microscope-live")
            put("run_id", plan.runId)
            put("model", Build.MODEL)
            put("android_release", Build.VERSION.RELEASE)
            put("listed_ids", JSONArray(listed))
            put("rear_ids", JSONArray(rear.sorted()))
            put("stream_ms", plan.streamMs)
            put("burst_frames", plan.burst)
            put("cameras", cameras)
        }
        val file = File(outDir, "microscope_live_${plan.runId}.json")
        val tmp = File(outDir, file.name + ".tmp")
        tmp.writeText(report.toString(2))
        check(tmp.renameTo(file)) { "cannot write $file" }
        return file
    }

    private fun runOne(plan: Plan, id: String): JSONObject {
        val out = JSONObject().put("camera_id", id)
        try {
            val size = station.open(id)
            out.put("width", size.w).put("height", size.h).put("open_attempts", station.openAttempts)
            val s = station.stream(plan.streamMs)
            out.put("stream", JSONObject().apply {
                put("frames", s.frames)
                put("elapsed_s", s.elapsedS)
                put("fps", s.fps)
                put("capture_failures", s.failures)
                put("work_ms_mean", s.workMsMean)
                put("work_ms_max", s.workMsMax)
            })
            out.put("burst", station.burst(File(outDir, "captures/${plan.runId}_cam$id"), plan.burst))
        } catch (e: Exception) {
            out.put("error", e.toString())
        } finally {
            station.close()
        }
        return out
    }
}
