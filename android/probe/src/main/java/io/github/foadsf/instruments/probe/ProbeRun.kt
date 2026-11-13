package io.github.foadsf.instruments.probe

import android.content.Context
import android.hardware.camera2.CameraManager
import android.util.Log
import io.github.foadsf.instruments.probe.core.EventLog
import io.github.foadsf.instruments.probe.core.Json
import io.github.foadsf.instruments.probe.core.Level
import io.github.foadsf.instruments.probe.core.TrialPlanner
import io.github.foadsf.instruments.probe.core.Verdicts
import java.io.File
import java.time.Instant

/**
 * One probe run: device, cameras, stream trials, compute. Each section is collected on its own,
 * so a failure in one is recorded under "probe_errors" and the others are still written.
 * Output (app-specific external storage, pulled with adb):
 *   probe_<run_id>.json   the report, written to a temporary name and renamed when complete;
 *   events_<run_id>.jsonl the structured event log.
 */
class ProbeRun(private val ctx: Context, private val runId: String, verbose: Boolean) {
    private val dir: File = ctx.getExternalFilesDir(null) ?: ctx.filesDir
    private val eventsFile = File(dir, "events_$runId.jsonl")
    val log = EventLog(runId, if (verbose) Level.DEBUG else Level.INFO, ::sink, { Instant.now().toString() })
    private val errors = mutableListOf<Map<String, Any?>>()

    private fun sink(level: Level, line: String) {
        Log.println(if (level >= Level.WARN) Log.WARN else Log.INFO, TAG, line)
        runCatching { eventsFile.appendText(line + "\n") }
    }

    fun execute(): File {
        log.info("probe.start") { mapOf("app_version" to BuildConfig.VERSION_NAME, "dir" to dir.path) }
        val report = linkedMapOf<String, Any?>(
            "schema" to SCHEMA,
            "run_id" to runId,
            "created_utc" to Instant.now().toString(),
            "app_version" to BuildConfig.VERSION_NAME,
        )
        report["device"] = section("device") { DeviceFacts.collect(ctx) }
        val manager = ctx.getSystemService(CameraManager::class.java)
        val scan = CameraScan(manager, log)
        val entries = section("camera_scan") { scan.scan() } ?: emptyList()
        report["cameras"] = linkedMapOf(
            "listed_ids" to entries.filter { it.listed }.map { it.id },
            "scanned_id_range" to listOf(CameraScan.SCAN_RANGE.first, CameraScan.SCAN_RANGE.last),
            "concurrent_id_sets" to scan.concurrentIdSets(),
            "entries" to section("camera_json") { scan.toJson(entries) },
        )
        val infos = scan.cameraInfo(entries)
        val results = section("stream_trials") { StreamTrials(manager, log).runAll(TrialPlanner.plan(infos)) } ?: emptyList()
        report["stream_trials"] = results.map(Verdicts::toJson)
        report["dual_physical_streams"] = Verdicts.dualStreamAnswer(results, infos.count { it.isLogicalMulti })
        report["compute"] = section("compute") { ComputeFacts.collect(ctx) }
        report["probe_errors"] = errors
        return write(report).also { f -> log.info("probe.done") { mapOf("report" to f.path, "errors" to errors.size) } }
    }

    private fun <T> section(name: String, block: () -> T): T? = try {
        block()
    } catch (e: Throwable) {
        log.error("probe.section_failed") { mapOf("section" to name, "error" to e.toString()) }
        errors += mapOf("section" to name, "error" to e.toString())
        null
    }

    private fun write(report: Map<String, Any?>): File {
        val tmp = File(dir, "probe_$runId.json.tmp")
        val out = File(dir, "probe_$runId.json")
        tmp.writeText(Json.write(report) + "\n")
        check(tmp.renameTo(out)) { "rename failed: $tmp -> $out" }
        return out
    }

    companion object {
        const val TAG = "instruments.probe"
        const val SCHEMA = "instruments.probe/1"
    }
}
