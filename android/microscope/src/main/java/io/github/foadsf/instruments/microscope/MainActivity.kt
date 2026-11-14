package io.github.foadsf.instruments.microscope

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import io.github.foadsf.instruments.microscope.core.CameraChoice
import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors

/**
 * Live view of one camera (camera 2, the Note8 telephoto, by default), digital zoom, frame rate
 * and sharpness readouts, and raw bursts for the fusion units. Started by hand it is a viewer;
 * started over adb with the extra `run_id` it runs [RunMode] and finishes. Extras: `camera`,
 * `run_id`, `cameras` (comma-separated, run mode), `stream_ms`, `burst`.
 */
class MainActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var station: Station
    private lateinit var view: ImageView
    private lateinit var readout: TextView
    private var bitmap: Bitmap? = null
    private var cameraId: String? = null
    private var message = ""
    @Volatile private var torchOn = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        // An adb evidence run must stay in the foreground: behind the lock screen the app counts as
        // background and the camera service refuses the next camera ("Access ... restricted").
        // Showing over the lock screen does not unlock the phone; the viewer itself never does it.
        if (isRunMode()) setShowWhenLocked(true)
        station = Station(applicationContext) { px, w, h -> ui.post { draw(px, w, h) } }
        view = ImageView(this).apply { scaleType = ImageView.ScaleType.FIT_CENTER; setBackgroundColor(Color.BLACK) }
        readout = TextView(this).apply { setTextColor(Color.WHITE); setShadowLayer(3f, 0f, 0f, Color.BLACK); setPadding(16, 16, 16, 16) }
        val buttons = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(button("Camera") { nextCamera() })
            addView(button("Zoom") { station.zoom = if (station.zoom >= 4) 1 else station.zoom * 2 })
            addView(button("Save") { saveBurst(listOfNotNull(cameraId)) })
            addView(button("Pair") { saveBurst(PAIR) })
            addView(button("Torch") { toggleTorch() })
        }
        setContentView(FrameLayout(this).apply {
            addView(view)
            addView(readout, FrameLayout.LayoutParams(-2, -2, Gravity.TOP or Gravity.START))
            addView(buttons, FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL))
        })
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), REQUEST_CAMERA)
        } else if (savedInstanceState == null) start()
    }

    // Starts with or without the permission: without it the camera error is what gets shown.
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        if (requestCode == REQUEST_CAMERA) start()
    }

    // A viewer must not hold the camera in the background; run mode finishes on its own.
    override fun onStop() {
        super.onStop()
        if (!isRunMode()) worker.execute { station.close() }
    }

    override fun onRestart() {
        super.onRestart()
        if (!isRunMode()) worker.execute { cameraId?.let(::openCamera) }
    }

    private fun isRunMode() = intent.hasExtra(EXTRA_RUN_ID)

    override fun onDestroy() {
        worker.execute { station.release() }
        worker.shutdown()
        super.onDestroy()
    }

    private fun start() {
        val runId = intent.getStringExtra(EXTRA_RUN_ID)
        if (runId != null) return runEvidence(runId)
        worker.execute {
            val (listed, rear) = station.cameras()
            openCamera(CameraChoice.pickCamera(listed, rear, intent.getStringExtra(EXTRA_CAMERA)))
        }
        tick()
    }

    private fun runEvidence(runId: String) {
        message = "Run $runId ..."
        tick()
        worker.execute {
            val (listed, rear) = station.cameras()
            val ids = intent.getStringExtra(EXTRA_CAMERAS)?.split(',')?.map { it.trim() }?.filter { it.isNotEmpty() }
                ?: listOfNotNull(CameraChoice.pickCamera(listed, rear, intent.getStringExtra(EXTRA_CAMERA)))
            val series = intent.getIntExtra(EXTRA_SERIES, 0)
            val result = if (series > 0) runCatching { runSeries(runId, ids, series) } else {
                val plan = RunMode.Plan(runId, ids, intent.getLongExtra(EXTRA_STREAM_MS, 10_000L),
                    intent.getIntExtra(EXTRA_BURST, 16), intent.getStringExtra(EXTRA_TORCH) ?: "off",
                    intent.getStringExtra(EXTRA_OIS) == "off")
                runCatching { RunMode(station, outDir()).execute(plan) }
            }
            ui.post {
                message = result.fold({ "Done: ${it.name}" }, { "Run failed: $it" })
                finish()
            }
        }
    }

    /** The calibration series (camera-calibration.md); OIS off unless `ois=default`. */
    private fun runSeries(runId: String, ids: List<String>, poses: Int): File {
        val focus = intent.getFloatExtra(EXTRA_FOCUS, -1f).takeIf { it >= 0f }
        val plan = SeriesMode.Plan(runId, ids, poses, intent.getLongExtra(EXTRA_STILL_MS, 1000L),
            burst = intent.getIntExtra(EXTRA_BURST, 4), focusDiopters = focus,
            oisOff = intent.getStringExtra(EXTRA_OIS) != "default")
        message = "Calibration series: hold each pose still; a beep means move on"
        return SeriesMode(station, SensorRecorder(applicationContext), outDir()).execute(plan)
    }

    /** On the worker thread. */
    private fun openCamera(id: String?) {
        if (id == null) { message = "No rear camera"; return }
        cameraId = id
        torchOn = false
        message = runCatching { station.open(id) }.fold({ "" }, { "Camera $id: ${it.message}" })
    }

    private fun nextCamera() = worker.execute {
        val (listed, rear) = station.cameras()
        val order = listed.filter { it in rear }
        if (order.isNotEmpty()) openCamera(order[(order.indexOf(cameraId) + 1) % order.size])
    }

    // Opening another camera turns the LED off (Station.open), so the label follows the state.
    private fun toggleTorch() = worker.execute {
        val on = !torchOn
        message = runCatching { station.setTorch(if (on) "on" else "off") }.fold(
            { if (it.has("error")) "Torch: ${it.getString("error")}" else { torchOn = on; if (on) "Torch on (${it.getString("method")})" else "" } },
            { "Torch: ${it.message}" })
    }

    private fun saveBurst(ids: List<String>) = worker.execute {
        val stamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss"))
        val back = cameraId
        message = "Saving ..."
        message = runCatching {
            val bursts = ids.map { id ->
                if (station.openId != id) station.open(id).also { station.stream(WARM_MS) }
                station.burst(File(outDir(), "captures/${stamp}_cam$id"), 16).getInt("frames")
            }
            "Saved $stamp: ${ids.zip(bursts).joinToString { (id, n) -> "cam $id $n frames" }}"
        }.getOrElse { "Save failed: ${it.message}" }
        if (back != null && station.openId != back) openCamera(back)
    }

    private fun draw(px: IntArray, w: Int, h: Int) {
        val b = bitmap?.takeIf { it.width == w && it.height == h }
            ?: Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888).also { bitmap = it; view.setImageBitmap(it) }
        b.setPixels(px, 0, w, 0, 0, w, h)
        view.invalidate()
        station.previewDone()
    }

    private fun tick() {
        val s = station.size
        val line = if (s == null) "" else "cam ${station.openId} · ${s.w}x${s.h} · %.1f fps · sharpness %.0f · zoom %dx"
            .format(station.fps, station.sharpness, station.zoom)
        readout.text = listOf(line, message).filter { it.isNotEmpty() }.joinToString("\n")
        if (!isFinishing) ui.postDelayed(::tick, TICK_MS)
    }

    private fun outDir(): File = getExternalFilesDir(null) ?: filesDir

    private fun button(label: String, onClick: () -> Unit) = Button(this).apply { text = label; setOnClickListener { onClick() } }

    private companion object {
        const val EXTRA_CAMERA = "camera"
        const val EXTRA_CAMERAS = "cameras"
        const val EXTRA_RUN_ID = "run_id"
        const val EXTRA_STREAM_MS = "stream_ms"
        const val EXTRA_BURST = "burst"
        const val EXTRA_TORCH = "torch"
        const val EXTRA_OIS = "ois"
        const val EXTRA_SERIES = "series"
        const val EXTRA_STILL_MS = "still_ms"
        const val EXTRA_FOCUS = "focus_diopters"
        const val REQUEST_CAMERA = 1
        const val TICK_MS = 500L
        const val WARM_MS = 2000L
        val PAIR = listOf("0", "2")
    }
}
