package io.github.foadsf.instruments.probe.core

import org.junit.Assert.assertEquals
import org.junit.Test

class VerdictsTest {
    private val size = Size2(1440, 1080)
    private fun plan(kind: TrialKind, open: String = "20", n: Int = if (kind == TrialKind.PHYSICAL_PAIR) 2 else 1) =
        TrialPlan(open, kind, List(n) { StreamSpec(if (kind == TrialKind.CONTROL) null else "$it", size) })

    private fun result(kind: TrialKind, configured: Boolean, vararg frames: Int, open: String = "20") =
        TrialResult(plan(kind, open, frames.size), "true", configured, frames.toList(), 2000, 0, null)

    @Test
    fun verdictBoundaries() {
        assertEquals(Verdict.CONFIGURE_FAILED, Verdicts.of(result(TrialKind.PHYSICAL_PAIR, false, 0, 0)))
        assertEquals(Verdict.WORKS, Verdicts.of(result(TrialKind.PHYSICAL_PAIR, true, 10, 10)))
        assertEquals(Verdict.PARTIAL_FRAMES, Verdicts.of(result(TrialKind.PHYSICAL_PAIR, true, 10, 9)))
        assertEquals(Verdict.PARTIAL_FRAMES, Verdicts.of(result(TrialKind.PHYSICAL_PAIR, true, 30, 0)))
        assertEquals(Verdict.NO_FRAMES, Verdicts.of(result(TrialKind.PHYSICAL_PAIR, true, 0, 0)))
    }

    @Test
    fun noLogicalCameraIsNotApplicable() {
        assertEquals("not_applicable", Verdicts.dualStreamAnswer(listOf(result(TrialKind.CONTROL, true, 60, open = "0")), 0))
    }

    @Test
    fun anyWorkingPairIsYes() {
        val rs = listOf(result(TrialKind.CONTROL, true, 60), result(TrialKind.PHYSICAL_PAIR, true, 30, 30))
        assertEquals("yes", Verdicts.dualStreamAnswer(rs, 1))
    }

    @Test
    fun failedPairsAreNoOnlyWhenTheControlWorked() {
        val pairFailed = result(TrialKind.PHYSICAL_PAIR, false, 0, 0)
        assertEquals("no", Verdicts.dualStreamAnswer(listOf(result(TrialKind.CONTROL, true, 60), pairFailed), 1))
        assertEquals("cannot_tell", Verdicts.dualStreamAnswer(listOf(result(TrialKind.CONTROL, false, 0), pairFailed), 1))
        assertEquals("cannot_tell", Verdicts.dualStreamAnswer(listOf(result(TrialKind.CONTROL, true, 60)), 1))
    }

    @Test
    fun failedResultKeepsOneZeroPerStream() {
        val r = TrialResult.failed(plan(TrialKind.PHYSICAL_PAIR), "open: timeout")
        assertEquals(listOf(0, 0), r.frames)
        assertEquals(Verdict.CONFIGURE_FAILED, Verdicts.of(r))
        assertEquals("CONFIGURE_FAILED", Verdicts.toJson(r)["verdict"])
    }
}
