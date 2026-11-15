package io.github.foadsf.instruments.microscope.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FrameGateTest {
    private val ms = 1_000_000L
    private val gate = FrameGate(rateRadS = 0.03, minGapNs = 500 * ms, padNs = 5 * ms, minSamples = 3)

    /** Gyro samples every 2.5 ms (400 Hz) from [from] to [to] with the given rate. */
    private fun gyro(from: Long, to: Long, rate: (Long) -> Double) =
        (from..to step (5 * ms / 2)).map { FrameGate.Rate(it, rate(it)) }

    @Test fun calmExposureIsKept() {
        val s = gyro(0, 200 * ms) { 0.01 }
        val d = gate.decide(100 * ms, 10 * ms, 25 * ms, s, lastKeptNs = null)
        assertTrue(d.keep)
        assertEquals("ok", d.reason)
        assertEquals(0.01, d.maxRate, 1e-12)
    }

    @Test fun aJerkInsideTheReadoutRejects() {
        // Exposure 10 ms + readout 25 ms from t = 100 ms: a spike at 130 ms is inside the frame.
        val s = gyro(0, 200 * ms) { t -> if (t in 129 * ms..131 * ms) 0.2 else 0.01 }
        val d = gate.decide(100 * ms, 10 * ms, 25 * ms, s, lastKeptNs = null)
        assertTrue(!d.keep)
        assertTrue(d.reason.startsWith("gyro"))
    }

    @Test fun aJerkOutsideTheFrameDoesNotReject() {
        val s = gyro(0, 200 * ms) { t -> if (t in 160 * ms..170 * ms) 0.2 else 0.01 }
        assertTrue(gate.decide(100 * ms, 10 * ms, 25 * ms, s, lastKeptNs = null).keep)
    }

    @Test fun tooFewSamplesCannotShowCalm() {
        // Negative control: no gyro data over the frame must never pass as calm.
        val s = gyro(0, 90 * ms) { 0.0 } + gyro(150 * ms, 200 * ms) { 0.0 }
        val d = gate.decide(100 * ms, 10 * ms, 25 * ms, s, lastKeptNs = null)
        assertTrue(!d.keep)
        assertTrue(d.reason.startsWith("samples"))
    }

    @Test fun gatesParsePerCamera() {
        assertEquals(mapOf("0" to 0.04, "2" to 0.02), FrameGate.parseGates("0:0.04,2:0.02"))
        for (bad in listOf("0.04", "0:", "0:-1", "0:0.04,0:0.02", "0:x", "")) {
            assertTrue(bad, runCatching { FrameGate.parseGates(bad) }.isFailure)
        }
    }

    @Test fun framesCloserThanTheGapAreSkipped() {
        val s = gyro(0, 1000 * ms) { 0.0 }
        assertTrue(!gate.decide(700 * ms, 10 * ms, 25 * ms, s, lastKeptNs = 300 * ms).keep)
        assertTrue(gate.decide(900 * ms, 10 * ms, 25 * ms, s, lastKeptNs = 300 * ms).keep)
    }
}
