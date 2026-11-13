package io.github.foadsf.instruments.probe

import android.annotation.SuppressLint
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureFailure
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import io.github.foadsf.instruments.probe.core.EventLog
import io.github.foadsf.instruments.probe.core.TrialPlan
import io.github.foadsf.instruments.probe.core.TrialResult
import io.github.foadsf.instruments.probe.core.Verdicts
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicIntegerArray

/**
 * Runs each [TrialPlan] for real: opens the camera, asks isSessionConfigurationSupported, then
 * configures the session anyway and counts the frames that arrive on every stream in
 * [STREAM_MS]. The query and the real attempt are recorded separately because a HAL can answer
 * one and do the other.
 */
class StreamTrials(private val manager: CameraManager, private val log: EventLog) {
    private val thread = HandlerThread("probe-camera").apply { start() }
    private val handler = Handler(thread.looper)
    private val executor = Executor { handler.post(it) }

    fun runAll(plans: List<TrialPlan>): List<TrialResult> = try {
        plans.groupBy { it.openId }.flatMap { (id, group) -> runOnDevice(id, group) }
    } finally {
        thread.quitSafely()
    }

    private fun runOnDevice(id: String, group: List<TrialPlan>): List<TrialResult> {
        val (device, error) = open(id)
        if (device == null) {
            log.error("trial.open_failed") { mapOf("id" to id, "error" to error) }
            return group.map { TrialResult.failed(it, "open: $error") }
        }
        return try {
            group.map { plan -> runOne(device, plan).also { r -> log.info("trial.done") { Verdicts.toJson(r) } } }
        } finally {
            device.close()
        }
    }

    // MainActivity asks for CAMERA before the probe starts; without it openCamera throws and the
    // SecurityException is recorded as the trial's error.
    @SuppressLint("MissingPermission")
    private fun open(id: String): Pair<CameraDevice?, String?> {
        val latch = CountDownLatch(1)
        var device: CameraDevice? = null
        var error: String? = null
        val callback = object : CameraDevice.StateCallback() {
            override fun onOpened(d: CameraDevice) { device = d; latch.countDown() }
            override fun onDisconnected(d: CameraDevice) { error = "disconnected"; d.close(); latch.countDown() }
            override fun onError(d: CameraDevice, code: Int) { error = "onError $code"; d.close(); latch.countDown() }
        }
        try {
            manager.openCamera(id, executor, callback)
        } catch (e: Exception) {
            return null to e.toString()
        }
        if (!latch.await(OPEN_TIMEOUT_S, TimeUnit.SECONDS)) return null to "open timeout"
        return device to error
    }

    private fun runOne(device: CameraDevice, plan: TrialPlan): TrialResult {
        val readers = plan.streams.map { ImageReader.newInstance(it.size.w, it.size.h, ImageFormat.YUV_420_888, 4) }
        val counts = AtomicIntegerArray(readers.size)
        readers.forEachIndexed { i, r ->
            r.setOnImageAvailableListener({ rr -> rr.acquireNextImage()?.close(); counts.incrementAndGet(i) }, handler)
        }
        return try {
            val outputs = plan.streams.mapIndexed { i, s ->
                OutputConfiguration(readers[i].surface).apply { s.physicalId?.let(::setPhysicalCameraId) }
            }
            stream(device, plan, readers, outputs, counts)
        } catch (e: Exception) {
            log.error("trial.exception") { mapOf("label" to plan.label, "error" to e.toString()) }
            TrialResult.failed(plan, e.toString())
        } finally {
            readers.forEach { it.close() }
        }
    }

    private fun stream(
        device: CameraDevice, plan: TrialPlan, readers: List<ImageReader>,
        outputs: List<OutputConfiguration>, counts: AtomicIntegerArray,
    ): TrialResult {
        val waiter = SessionWaiter()
        val config = SessionConfiguration(SessionConfiguration.SESSION_REGULAR, outputs, executor, waiter)
        val query = supportQuery(device, config)
        log.debug("trial.query") { mapOf("label" to plan.label, "supported" to query) }
        device.createCaptureSession(config)
        val session = waiter.awaitConfigured()
            ?: return TrialResult.failed(plan, waiter.failure ?: "configure timeout", query)
        val failures = AtomicInteger()
        val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
            .apply { readers.forEach { addTarget(it.surface) } }.build()
        val start = SystemClock.elapsedRealtime()
        session.setRepeatingRequest(request, object : CameraCaptureSession.CaptureCallback() {
            override fun onCaptureFailed(s: CameraCaptureSession, r: CaptureRequest, f: CaptureFailure) {
                failures.incrementAndGet()
            }
        }, handler)
        Thread.sleep(STREAM_MS)
        session.stopRepeating()
        val elapsed = SystemClock.elapsedRealtime() - start
        session.close()
        waiter.awaitClosed()
        val frames = (0 until counts.length()).map { counts.get(it) }
        return TrialResult(plan, query, true, frames, elapsed, failures.get(), null)
    }

    private fun supportQuery(device: CameraDevice, config: SessionConfiguration): String = try {
        device.isSessionConfigurationSupported(config).toString()
    } catch (e: UnsupportedOperationException) {
        "unknown (query not supported by this HAL)"
    } catch (e: Exception) {
        "error: ${e.javaClass.simpleName}: ${e.message}"
    }

    private class SessionWaiter : CameraCaptureSession.StateCallback() {
        private val configuredLatch = CountDownLatch(1)
        private val closedLatch = CountDownLatch(1)
        @Volatile private var session: CameraCaptureSession? = null
        @Volatile var failure: String? = null

        override fun onConfigured(s: CameraCaptureSession) { session = s; configuredLatch.countDown() }
        override fun onConfigureFailed(s: CameraCaptureSession) { failure = "onConfigureFailed"; configuredLatch.countDown() }
        override fun onClosed(s: CameraCaptureSession) { closedLatch.countDown() }

        fun awaitConfigured(): CameraCaptureSession? =
            if (configuredLatch.await(CONFIGURE_TIMEOUT_S, TimeUnit.SECONDS)) session else null

        fun awaitClosed() { closedLatch.await(CLOSE_TIMEOUT_S, TimeUnit.SECONDS) }
    }

    companion object {
        const val OPEN_TIMEOUT_S = 5L
        const val CONFIGURE_TIMEOUT_S = 5L
        const val CLOSE_TIMEOUT_S = 3L
        const val STREAM_MS = 2000L
    }
}
