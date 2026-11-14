package io.github.foadsf.instruments.microscope

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureFailure
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import io.github.foadsf.instruments.microscope.core.CameraChoice
import io.github.foadsf.instruments.microscope.core.PlaneView
import io.github.foadsf.instruments.microscope.core.Size2
import io.github.foadsf.instruments.microscope.core.YuvFrames
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** What the capture result reported for one frame, matched to the image by sensor timestamp. */
data class FrameMeta(val focusDiopters: Float?, val afMode: Int?, val afState: Int?, val exposureNs: Long?,
                     val frameDurationNs: Long?, val oisMode: Int? = null)

/**
 * One camera, one YUV_420_888 stream (the camera 2 bridge accepts exactly one). Every frame is
 * packed to I420 into a buffer that is reused for the next frame and handed to [onFrame] on the
 * image thread. [open] and [close] block: call them from a worker thread, never the UI thread.
 */
class LiveCamera(context: Context, private val onFrame: (i420: ByteArray, w: Int, h: Int, tsNs: Long) -> Unit) {
    private val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
    private val camThread = HandlerThread("mic-camera").apply { start() }
    private val camHandler = Handler(camThread.looper)
    private val executor = Executor { camHandler.post(it) }
    private val imgThread = HandlerThread("mic-frames").apply { start() }
    private val imgHandler = Handler(imgThread.looper)

    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null
    private var packed = ByteArray(0)
    private val meta = ConcurrentHashMap<Long, FrameMeta>()
    val failures = AtomicInteger()
    var openId: String? = null
        private set
    var size: Size2? = null
        private set

    fun listed(): List<String> = manager.cameraIdList.toList()

    fun rear(): Set<String> = listed().filter {
        runCatching { manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) }.getOrNull() ==
            CameraCharacteristics.LENS_FACING_BACK
    }.toSet()

    fun yuvSizes(id: String): List<Size2> =
        manager.getCameraCharacteristics(id).get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?.getOutputSizes(ImageFormat.YUV_420_888)?.map { Size2(it.width, it.height) }.orEmpty()

    fun meta(tsNs: Long): FrameMeta? = meta[tsNs]

    /** Cameras whose characteristics say they own a flash unit. */
    fun flashIds(): List<String> = listed().filter {
        runCatching { manager.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) }.getOrNull() == true
    }

    /** Optical stabilisation off in every request (set before [open]): on a stand, OIS can only
     *  move the image between burst frames. The result's mode is recorded per frame. */
    @Volatile var oisOff = false

    /** Manual focus in diopters for every request (AF off), set before [open]; null = the camera's AF.
     *  The bridged camera 2 ignores it; the reported focus per frame shows what each camera did. */
    @Volatile var focusDiopters: Float? = null

    /** FLASH_MODE_TORCH in the repeating request of the open camera (re-issued at once). */
    @Volatile var flashTorch = false
        private set

    fun setFlashTorch(on: Boolean) {
        flashTorch = on
        val dev = device ?: return
        val ir = reader ?: return
        session?.setRepeatingRequest(request(dev, ir), resultCallback, camHandler)
    }

    /** The LED through the torch API, independent of any open camera's requests. Throws if refused. */
    fun setTorchMode(id: String, on: Boolean) = manager.setTorchMode(id, on)

    @Volatile private var workNs = 0L
    @Volatile private var workMaxNs = 0L
    @Volatile private var workFrames = 0

    fun resetWork() { workNs = 0L; workMaxNs = 0L; workFrames = 0 }

    /** Mean and max milliseconds per frame spent in [deliver] since [resetWork]. */
    fun work(): Pair<Double, Double> =
        (if (workFrames > 0) workNs / 1e6 / workFrames else 0.0) to workMaxNs / 1e6

    /** How many openCamera attempts the last [open] needed (the HAL can refuse just after a close). */
    var openAttempts = 0
        private set

    /** Opens [id] and streams the first size the camera accepts. Throws with the reason on failure. */
    fun open(id: String): Size2 {
        close()
        val dev = openWithRetry(id)
        device = dev
        openId = id
        val tried = ArrayList<String>()
        for (s in CameraChoice.sizeCandidates(yuvSizes(id))) {
            val ir = ImageReader.newInstance(s.w, s.h, ImageFormat.YUV_420_888, MAX_IMAGES)
            val configured = configure(dev, ir)
            if (configured == null) {
                tried.add("${s.w}x${s.h}")
                ir.close()
                continue
            }
            reader = ir
            session = configured
            size = s
            packed = ByteArray(s.w * s.h * 3 / 2)
            ir.setOnImageAvailableListener({ r -> deliver(r, s) }, imgHandler)
            configured.setRepeatingRequest(request(dev, ir), resultCallback, camHandler)
            return s
        }
        close()
        error("camera $id refused every size: ${tried.joinToString()}")
    }

    fun close() {
        runCatching { session?.stopRepeating() }
        runCatching { session?.close() }
        runCatching { device?.close() }
        // Let in-flight image callbacks finish before the reader goes away.
        val drained = CountDownLatch(1)
        imgHandler.post { drained.countDown() }
        drained.await(1, TimeUnit.SECONDS)
        runCatching { reader?.close() }
        session = null
        device = null
        reader = null
        openId = null
        size = null
        flashTorch = false
        meta.clear()
        failures.set(0)
    }

    fun release() {
        close()
        camThread.quitSafely()
        imgThread.quitSafely()
    }

    private fun deliver(r: ImageReader, s: Size2) {
        val img = runCatching { r.acquireLatestImage() }.getOrNull() ?: return
        val t0 = System.nanoTime()
        try {
            val p = img.planes
            YuvFrames.packI420(
                PlaneView(p[0].buffer, p[0].rowStride, p[0].pixelStride),
                PlaneView(p[1].buffer, p[1].rowStride, p[1].pixelStride),
                PlaneView(p[2].buffer, p[2].rowStride, p[2].pixelStride),
                s.w, s.h, packed,
            )
            onFrame(packed, s.w, s.h, img.timestamp)
        } finally {
            img.close()
            val dt = System.nanoTime() - t0
            workNs += dt
            workFrames++
            if (dt > workMaxNs) workMaxNs = dt
        }
    }

    private fun request(dev: CameraDevice, ir: ImageReader): CaptureRequest =
        dev.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
            addTarget(ir.surface)
            if (oisOff) set(CaptureRequest.LENS_OPTICAL_STABILIZATION_MODE, CaptureRequest.LENS_OPTICAL_STABILIZATION_MODE_OFF)
            focusDiopters?.let {
                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF)
                set(CaptureRequest.LENS_FOCUS_DISTANCE, it)
            }
            if (flashTorch) {
                set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
                set(CaptureRequest.FLASH_MODE, CaptureRequest.FLASH_MODE_TORCH)
            }
        }.build()

    private val resultCallback = object : CameraCaptureSession.CaptureCallback() {
        override fun onCaptureCompleted(s: CameraCaptureSession, req: CaptureRequest, r: TotalCaptureResult) {
            val ts = r.get(CaptureResult.SENSOR_TIMESTAMP) ?: return
            meta[ts] = FrameMeta(r.get(CaptureResult.LENS_FOCUS_DISTANCE), r.get(CaptureResult.CONTROL_AF_MODE),
                r.get(CaptureResult.CONTROL_AF_STATE), r.get(CaptureResult.SENSOR_EXPOSURE_TIME),
                r.get(CaptureResult.SENSOR_FRAME_DURATION), r.get(CaptureResult.LENS_OPTICAL_STABILIZATION_MODE))
            if (meta.size > META_KEEP) meta.keys.sorted().take(meta.size - META_KEEP).forEach(meta::remove)
        }

        override fun onCaptureFailed(s: CameraCaptureSession, req: CaptureRequest, f: CaptureFailure) {
            failures.incrementAndGet()
        }
    }

    /**
     * On the Note8, opening camera 2 within ~50 ms of closing camera 0 failed in the camera service
     * ("Could not initialize client from HAL", reported as CAMERA_DISABLED); retry a few times.
     */
    private fun openWithRetry(id: String): CameraDevice {
        var last: Exception? = null
        for (attempt in 1..OPEN_ATTEMPTS) {
            openAttempts = attempt
            try {
                return openDevice(id)
            } catch (e: Exception) {
                last = e
                Thread.sleep(RETRY_MS)
            }
        }
        throw last ?: IllegalStateException("camera $id: open failed")
    }

    // MainActivity asks for CAMERA first; without it openCamera throws and the reason is reported.
    @SuppressLint("MissingPermission")
    private fun openDevice(id: String): CameraDevice {
        val latch = CountDownLatch(1)
        var dev: CameraDevice? = null
        var err: String? = null
        manager.openCamera(id, executor, object : CameraDevice.StateCallback() {
            override fun onOpened(d: CameraDevice) { dev = d; latch.countDown() }
            override fun onDisconnected(d: CameraDevice) { err = "disconnected"; d.close(); latch.countDown() }
            override fun onError(d: CameraDevice, code: Int) { err = "camera error $code"; d.close(); latch.countDown() }
        })
        if (!latch.await(TIMEOUT_S, TimeUnit.SECONDS)) error("camera $id: open timed out")
        return dev ?: error("camera $id: ${err ?: "open failed"}")
    }

    private fun configure(dev: CameraDevice, ir: ImageReader): CameraCaptureSession? {
        val latch = CountDownLatch(1)
        var result: CameraCaptureSession? = null
        val cb = object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(s: CameraCaptureSession) { result = s; latch.countDown() }
            override fun onConfigureFailed(s: CameraCaptureSession) { latch.countDown() }
        }
        dev.createCaptureSession(SessionConfiguration(SessionConfiguration.SESSION_REGULAR,
            listOf(OutputConfiguration(ir.surface)), executor, cb))
        latch.await(TIMEOUT_S, TimeUnit.SECONDS)
        return result
    }

    private companion object {
        const val MAX_IMAGES = 4
        const val META_KEEP = 120
        const val TIMEOUT_S = 5L
        const val OPEN_ATTEMPTS = 3
        const val RETRY_MS = 1000L
    }
}
