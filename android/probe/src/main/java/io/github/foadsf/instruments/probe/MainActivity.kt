package io.github.foadsf.instruments.probe

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import kotlin.random.Random

/**
 * One button, one text view. Started from adb (`tools/probe/run_probe.py`) with the extras
 * `autorun` (Boolean), `run_id` (String) and `verbose` (Boolean); started by hand, the button
 * runs the same probe.
 */
class MainActivity : Activity() {
    private lateinit var button: Button
    private lateinit var text: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        button = Button(this).apply { text = "Run probe"; setOnClickListener { start() } }
        text = TextView(this).apply { setTextIsSelectable(true); setPadding(24, 24, 24, 24) }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(button)
            addView(ScrollView(this@MainActivity).apply { addView(text) })
        }
        setContentView(column)
        if (savedInstanceState == null && intent.getBooleanExtra(EXTRA_AUTORUN, false)) start()
    }

    private fun start() {
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            launch()
        } else {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), REQUEST_CAMERA)
        }
    }

    // Runs with or without the permission: without it, the camera errors are the result.
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        if (requestCode == REQUEST_CAMERA) launch()
    }

    private fun launch() {
        val runId = intent.getStringExtra(EXTRA_RUN_ID) ?: newRunId()
        val verbose = intent.getBooleanExtra(EXTRA_VERBOSE, false)
        button.isEnabled = false
        text.text = "Running probe $runId ..."
        Thread {
            val trials = intent.getStringExtra(EXTRA_TRIALS)
            val message = runCatching { ProbeRun(applicationContext, runId, verbose, trials).execute() }
                .fold({ f -> "Done.\n${f.path}\n\n${summary(f.readText())}" }, { e -> "Probe failed: $e" })
            runOnUiThread { text.text = message; button.isEnabled = true }
        }.start()
    }

    private fun summary(reportJson: String): String =
        reportJson.lineSequence().filter { line ->
            SUMMARY_KEYS.any { line.trimStart().startsWith("\"$it\"") }
        }.joinToString("\n") { it.trim() }

    private fun newRunId(): String =
        LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss")) + "-" +
            "%04x".format(Random.nextInt(0x10000))

    companion object {
        const val EXTRA_AUTORUN = "autorun"
        const val EXTRA_RUN_ID = "run_id"
        const val EXTRA_VERBOSE = "verbose"
        const val EXTRA_TRIALS = "trials"
        private const val REQUEST_CAMERA = 1
        private val SUMMARY_KEYS = listOf("model", "android_release", "listed_ids", "dual_physical_streams", "verdict")
    }
}
