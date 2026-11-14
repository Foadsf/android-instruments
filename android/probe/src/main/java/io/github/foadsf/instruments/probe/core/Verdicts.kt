package io.github.foadsf.instruments.probe.core

/** What happened when one [TrialPlan] was tried on the phone. */
data class TrialResult(
    val plan: TrialPlan,
    /** Result of CameraDevice.isSessionConfigurationSupported: "true", "false", "unknown ..." or "error: ...". */
    val supportedQuery: String,
    val configured: Boolean,
    /** Frames received per stream, in plan order. */
    val frames: List<Int>,
    val durationMs: Long,
    val captureFailures: Int,
    val error: String?,
) {
    companion object {
        fun failed(plan: TrialPlan, error: String, query: String = "not asked") =
            TrialResult(plan, query, false, List(plan.streams.size) { 0 }, 0, 0, error)
    }
}

enum class Verdict { WORKS, CONFIGURE_FAILED, NO_FRAMES, PARTIAL_FRAMES }

/** Turns trial results into the Gate 1 answer. Pure: tested on the JVM. */
object Verdicts {
    /** At least 5 frames per second on every stream over the 2 s window. */
    const val MIN_FRAMES = 10

    fun of(r: TrialResult): Verdict = when {
        !r.configured -> Verdict.CONFIGURE_FAILED
        r.frames.all { it >= MIN_FRAMES } -> Verdict.WORKS
        r.frames.all { it == 0 } -> Verdict.NO_FRAMES
        else -> Verdict.PARTIAL_FRAMES
    }

    /**
     * "yes" when any physical pair works; "no" when pairs were tried, none worked and the
     * logical control did work (so the failure is the pairing, not the camera); "cannot_tell"
     * when the control failed or no pair was tried on a logical camera; "not_applicable" when
     * the phone exposes no logical multi-camera.
     */
    fun dualStreamAnswer(results: List<TrialResult>, logicalMultiCameras: Int): String {
        if (logicalMultiCameras == 0) return "not_applicable"
        val pairs = results.filter { it.plan.kind == TrialKind.PHYSICAL_PAIR }
        if (pairs.any { of(it) == Verdict.WORKS }) return "yes"
        val controlsOk = results.filter { it.plan.kind == TrialKind.CONTROL }
            .groupBy { it.plan.openId }
            .filterValues { list -> list.any { of(it) == Verdict.WORKS } }.keys
        val testedWithControl = pairs.filter { it.plan.openId in controlsOk }
        return if (testedWithControl.isNotEmpty()) "no" else "cannot_tell"
    }

    fun toJson(r: TrialResult): Map<String, Any?> = linkedMapOf(
        "label" to r.plan.label,
        "open_id" to r.plan.openId,
        "second_open_id" to r.plan.secondOpenId,
        "kind" to r.plan.kind.name,
        "streams" to r.plan.streams.map { mapOf("physical_id" to it.physicalId, "size" to listOf(it.size.w, it.size.h)) },
        "supported_query" to r.supportedQuery,
        "configured" to r.configured,
        "frames" to r.frames,
        "duration_ms" to r.durationMs,
        "capture_failures" to r.captureFailures,
        "verdict" to of(r).name,
        "error" to r.error,
    )
}
