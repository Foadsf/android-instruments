package io.github.foadsf.instruments.microscope

import android.graphics.Bitmap
import io.github.foadsf.instruments.microscope.core.Sharpness
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Keeps the next [count] consecutive frames as raw packed I420 for the fusion units. Buffers are
 * allocated up front and [offer] (image thread) only copies into them, so the burst is not held
 * up by allocation or storage; the files (`frame_NN.yuv`, `preview.png`, `burst.json`) are
 * written in [finish], after the last frame. Frames offered after the burst is full or closed are
 * ignored.
 */
class BurstRecorder(private val dir: File, private val count: Int, private val w: Int, private val h: Int) {
    private val frames: Array<ByteArray>
    private val stamps = LongArray(count)
    private val full = CountDownLatch(1)
    private var taken = 0
    @Volatile private var closed = false

    init {
        require(count in 1..MAX_FRAMES) { "burst of $count frames is outside 1..$MAX_FRAMES" }
        check(dir.isDirectory || dir.mkdirs()) { "cannot create $dir" }
        frames = Array(count) { ByteArray(w * h * 3 / 2) }
    }

    /** Copies the camera's reused buffer; returns false once the burst is full or closed. */
    @Synchronized
    fun offer(i420: ByteArray, tsNs: Long): Boolean {
        if (closed || taken >= count) return false
        System.arraycopy(i420, 0, frames[taken], 0, frames[taken].size)
        stamps[taken] = tsNs
        if (++taken == count) full.countDown()
        return true
    }

    /** Waits for the burst, writes the files and returns the summary (also in burst.json). */
    fun finish(timeoutMs: Long, meta: (Long) -> FrameMeta?): JSONObject {
        val complete = full.await(timeoutMs, TimeUnit.MILLISECONDS)
        val n = synchronized(this) { closed = true; taken }
        val ts = stamps.copyOf(n)
        var writeError: String? = null
        for (i in 0 until n) {
            runCatching { File(dir, "frame_%02d.yuv".format(i)).writeBytes(frames[i]) }
                .onFailure { if (writeError == null) writeError = it.toString() }
        }
        val summary = JSONObject().apply {
            put("dir", dir.name)
            put("format", "I420")
            put("width", w)
            put("height", h)
            put("frames_requested", count)
            put("frames", n)
            put("complete", complete && writeError == null)
            put("timestamps_ns", JSONArray(ts.toList()))
            put("fps", if (n >= 2) (n - 1) * 1e9 / (ts[n - 1] - ts[0]) else 0.0)
            put("sharpness_frame0", if (n > 0) Sharpness.meanSquaredLaplacian(frames[0], w, Sharpness.centreHalf(w, h)) else JSONObject.NULL)
            put("sharpness_roi", "centre half")
            put("focus_distance_diopters", JSONArray(ts.map { meta(it)?.focusDiopters ?: JSONObject.NULL }))
            put("af_mode", JSONArray(ts.map { meta(it)?.afMode ?: JSONObject.NULL }))
            put("af_state", JSONArray(ts.map { meta(it)?.afState ?: JSONObject.NULL }))
            put("exposure_ns", JSONArray(ts.map { meta(it)?.exposureNs ?: JSONObject.NULL }))
            put("frame_duration_ns", JSONArray(ts.map { meta(it)?.frameDurationNs ?: JSONObject.NULL }))
            writeError?.let { put("write_error", it) }
        }
        if (n > 0) writeLumaPng(frames[0])
        File(dir, "burst.json").writeText(summary.toString(2))
        return summary
    }

    private fun writeLumaPng(i420: ByteArray) {
        val px = IntArray(w * h) { i -> (i420[i].toInt() and 0xff) * 0x010101 or (0xff shl 24) }
        val bmp = Bitmap.createBitmap(px, w, h, Bitmap.Config.ARGB_8888)
        File(dir, "preview.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bmp.recycle()
    }

    companion object {
        /** 32 frames at 1440x1080 hold 75 MB, within the app heap of the Note8 class of phone. */
        const val MAX_FRAMES = 32
    }
}
