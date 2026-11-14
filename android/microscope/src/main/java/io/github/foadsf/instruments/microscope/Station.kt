package io.github.foadsf.instruments.microscope

import android.content.Context
import android.os.Handler
import android.os.HandlerThread
import io.github.foadsf.instruments.microscope.core.FrameRate
import io.github.foadsf.instruments.microscope.core.Roi
import io.github.foadsf.instruments.microscope.core.Sharpness
import io.github.foadsf.instruments.microscope.core.Size2
import io.github.foadsf.instruments.microscope.core.YuvFrames
import org.json.JSONObject
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Everything between the camera and the screen: frame rate, sharpness of the visible area, the
 * colour preview and the burst recorder. open/close/stream/burst block: call them from one
 * worker thread. [onPreview] gets an ARGB buffer and must call [previewDone] when drawn.
 */
class Station(context: Context, private val onPreview: (IntArray, Int, Int) -> Unit) {
    /** [workMsMean] / [workMsMax]: time spent per frame on the image thread (pack, copies). */
    data class StreamStats(val frames: Int, val elapsedS: Double, val fps: Double, val failures: Int,
                           val workMsMean: Double, val workMsMax: Double)

    private val camera = LiveCamera(context, ::onFrame)
    private val rate = FrameRate()
    private val previewBusy = AtomicBoolean(false)
    private var previewBuf = IntArray(0)
    private var previewSrc = ByteArray(0)
    private val previewThread = HandlerThread("mic-preview").apply { start() }
    private val previewHandler = Handler(previewThread.looper)
    @Volatile private var recorder: BurstRecorder? = null
    @Volatile private var frames = 0
    @Volatile private var firstTs = 0L
    @Volatile private var lastTs = 0L
    @Volatile var zoom = 1
    @Volatile var sharpness = 0.0
        private set
    @Volatile var fps = 0.0
        private set

    val openId get() = camera.openId
    val size get() = camera.size
    val openAttempts get() = camera.openAttempts

    fun cameras(): Pair<List<String>, Set<String>> = camera.listed() to camera.rear()

    fun open(id: String): Size2 {
        frames = 0
        firstTs = 0L
        return camera.open(id)
    }

    fun close() {
        recorder = null
        camera.close()
    }

    fun release() {
        camera.release()
        previewThread.quitSafely()
    }

    fun previewDone() = previewBusy.set(false)

    /** Streams for [ms] and reports the frames that arrived in that time. */
    fun stream(ms: Long): StreamStats {
        val f0 = frames
        val t0 = lastTs
        camera.resetWork()
        Thread.sleep(ms)
        val n = frames - f0
        // Before the first frame the span starts at the first frame, which then is not an interval.
        val span = (lastTs - (if (t0 == 0L) firstTs else t0)) / 1e9
        val fps = if (span > 0) (n - (if (t0 == 0L) 1 else 0)) / span else 0.0
        val (mean, max) = camera.work()
        return StreamStats(n, ms / 1000.0, fps, camera.failures.get(), mean, max)
    }

    /** Records the next [count] frames into [dir] and returns the burst summary. */
    fun burst(dir: File, count: Int): JSONObject {
        val s = camera.size ?: error("no camera open")
        val r = BurstRecorder(dir, count, s.w, s.h)
        recorder = r
        val summary = r.finish(count * FRAME_BUDGET_MS + 2000) { camera.meta(it) }
        recorder = null
        return summary.put("camera_id", camera.openId)
    }

    private fun onFrame(i420: ByteArray, w: Int, h: Int, ts: Long) {
        if (frames == 0) firstTs = ts
        frames++
        lastTs = ts
        rate.add(ts)
        val r = recorder
        if (r != null) {  // a burst only copies: no preview or sharpness work that could slow it
            r.offer(i420, ts)
            return
        }
        if (frames % FPS_EVERY == 0) fps = rate.fps(FPS_WINDOW_NS)
        // The preview thread works on its own copy, at its own pace; frames it is too busy for
        // are simply not previewed, so the preview can never slow the camera stream.
        if (previewBusy.compareAndSet(false, true)) {
            if (previewSrc.size != i420.size) previewSrc = ByteArray(i420.size)
            System.arraycopy(i420, 0, previewSrc, 0, i420.size)
            previewHandler.post { renderPreview(w, h) }
        }
    }

    /** On the preview thread: colour preview and sharpness of the visible (zoomed) area. */
    private fun renderPreview(w: Int, h: Int) {
        val crop = YuvFrames.cropForZoom(w, h, zoom)
        sharpness = Sharpness.meanSquaredLaplacian(previewSrc, w, centreHalf(crop))
        val outH = PREVIEW_W * h / w
        if (previewBuf.size != PREVIEW_W * outH) previewBuf = IntArray(PREVIEW_W * outH)
        YuvFrames.previewArgb(previewSrc, w, h, crop, PREVIEW_W, outH, previewBuf)
        onPreview(previewBuf, PREVIEW_W, outH)
    }

    private fun centreHalf(c: Roi) =
        Roi(c.left + c.width / 4, c.top + c.height / 4, c.left + c.width / 4 + c.width / 2, c.top + c.height / 4 + c.height / 2)

    private companion object {
        const val PREVIEW_W = 960
        const val FPS_EVERY = 5
        const val FPS_WINDOW_NS = 2_000_000_000L
        const val FRAME_BUDGET_MS = 200L
    }
}
