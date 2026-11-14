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
import io.github.foadsf.instruments.probe.core.StreamSpec
import io.github.foadsf.instruments.probe.core.TrialKind
import io.github.foadsf.instruments.probe.core.TrialPlan
import io.github.foadsf.instruments.probe.core.TrialResult
import io.github.foadsf.instruments.probe.core.Verdicts
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicIntegerArray

/**
 * Runs each [TrialPlan] for real: opens the camera(s), asks isSessionConfigurationSupported, then
 * configures the session anyway and counts the frames that arrive on every stream in
 * [STREAM_MS]. The query and the real attempt are recorded separately because a HAL can answer
 * one and do the other. CONCURRENT_PAIR plans open two camera devices at the same time.
 */
class StreamTrials(
    private val manager: CameraManager,
    private val log: EventLog,
    private val streamMs: Long = STREAM_MS,
) {
    private val thread = HandlerThread("probe-camera").apply { start() }
    private val handler = Handler(thread.looper)
    private val executor = Executor { handler.post(it) }

    /** A configured, repeating session (or the reason it did not configure). */
    private class Started(val session: CameraCaptureSession?, val waiter: SessionWaiter, val query: String) {
        val failures = AtomicInteger()
    }

    fun runAll(plans: List<TrialPlan>): List<TrialResult> = try {
        val (concurrent, single) = plans.partition { it.kind == TrialKind.CONCURRENT_PAIR }
        single.groupBy { it.openId }.flatMap { (id, group) -> runOnDevice(id, group) } +
            concurrent.map { plan -> runConcurrent(plan).also { r -> log.info("trial.done") { Verdicts.toJson(r) } } }
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

    private fun readers(streams: List<StreamSpec>, counts: AtomicIntegerArray): List<ImageReader> =
        streams.mapIndexed { i, s ->
            ImageReader.newInstance(s.size.w, s.size.h, ImageFormat.YUV_420_888, 4).apply {
                setOnImageAvailableListener({ r -> r.acquireNextImage()?.close(); counts.incrementAndGet(i) }, handler)
            }
        }

    private fun runOne(device: CameraDevice, plan: TrialPlan): TrialResult {
        val counts = AtomicIntegerArray(plan.streams.size)
        val readers = readers(plan.streams, counts)
        return try {
            val s = start(device, plan.label, readers, plan.streams.map { it.physicalId })
            if (s.session == null) return TrialResult.failed(plan, s.waiter.failure ?: "configure timeout", s.query)
            val t0 = SystemClock.elapsedRealtime()
            Thread.sleep(streamMs)
            val elapsed = SystemClock.elapsedRealtime() - t0
            stop(s)
            TrialResult(plan, s.query, true, (0 until counts.length()).map(counts::get), elapsed, s.failures.get(), null)
        } catch (e: Exception) {
            log.error("trial.exception") { mapOf("label" to plan.label, "error" to e.toString()) }
            TrialResult.failed(plan, e.toString())
        } finally {
            readers.forEach { it.close() }
        }
    }

    private fun runConcurrent(plan: TrialPlan): TrialResult {
        val second = plan.secondOpenId ?: return TrialResult.failed(plan, "no second camera id")
        val (a, errA) = open(plan.openId)
        val (b, errB) = if (a != null) open(second) else null to "not tried"
        val counts = AtomicIntegerArray(2)
        val readers = readers(plan.streams, counts)
        try {
            if (a == null || b == null) return TrialResult.failed(plan, "open: ${plan.openId}=$errA, $second=$errB")
            val sa = start(a, plan.label, readers.subList(0, 1), listOf(null))
            val sb = start(b, plan.label, readers.subList(1, 2), listOf(null))
            val query = "${plan.openId}:${sa.query}; $second:${sb.query}"
            if (sa.session == null || sb.session == null) {
                stop(sa); stop(sb)
                return TrialResult.failed(plan, "configure: ${plan.openId}=${sa.waiter.failure}, $second=${sb.waiter.failure}", query)
            }
            val t0 = SystemClock.elapsedRealtime()
            Thread.sleep(streamMs)
            val elapsed = SystemClock.elapsedRealtime() - t0
            stop(sa); stop(sb)
            return TrialResult(plan, query, true, listOf(counts.get(0), counts.get(1)), elapsed, sa.failures.get() + sb.failures.get(), null)
        } catch (e: Exception) {
            log.error("trial.exception") { mapOf("label" to plan.label, "error" to e.toString()) }
            return TrialResult.failed(plan, e.toString())
        } finally {
            readers.forEach { it.close() }
            a?.close()
            b?.close()
        }
    }

    /** Configures one session over [readers] and starts a repeating preview request. */
    private fun start(device: CameraDevice, label: String, readers: List<ImageReader>, physicalIds: List<String?>): Started {
        val outputs = readers.mapIndexed { i, r ->
            OutputConfiguration(r.surface).apply { physicalIds[i]?.let(::setPhysicalCameraId) }
        }
        val waiter = SessionWaiter()
        val config = SessionConfiguration(SessionConfiguration.SESSION_REGULAR, outputs, executor, waiter)
        val query = supportQuery(device, config)
        log.debug("trial.query") { mapOf("label" to label, "camera" to device.id, "supported" to query) }
        device.createCaptureSession(config)
        val started = Started(waiter.awaitConfigured(), waiter, query)
        val session = started.session ?: return started
        val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
            .apply { readers.forEach { addTarget(it.surface) } }.build()
        session.setRepeatingRequest(request, object : CameraCaptureSession.CaptureCallback() {
            override fun onCaptureFailed(s: CameraCaptureSession, r: CaptureRequest, f: CaptureFailure) {
                started.failures.incrementAndGet()
            }
        }, handler)
        return started
    }

    private fun stop(s: Started) {
        val session = s.session ?: return
        runCatching { session.stopRepeating() }
        session.close()
        s.waiter.awaitClosed()
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
        /** Accepted range for a requested stream length (the `stream_ms` extra). */
        val STREAM_MS_RANGE = 500L..60_000L
    }
}
