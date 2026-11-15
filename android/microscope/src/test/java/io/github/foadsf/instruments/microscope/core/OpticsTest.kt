package io.github.foadsf.instruments.microscope.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

/** microscope-scale.md: hand calculations (Python, 2026-11-15) and the negative controls. */
class OpticsTest {
    private val cam0 = Optics.camera0()

    private fun rel(a: Double, b: Double) = abs(a / b - 1)

    @Test
    fun androidMicroscopeReferenceCase() {
        // Note10 main camera: f = 4.3 mm, 1.4 µm pixels, 80 mm (12.5 D): 0.0568x, 24.6 µm per pixel.
        val lens = Optics.Lens(4.3, 0.0014)
        assertTrue(rel(Optics.umPerPx(lens, 12.5)!!, 24.6465) < 0.001)
        assertTrue(rel(Optics.imageDistanceMm(lens, 12.5)!! / 80.0, 0.056803) < 0.001)
    }

    /** Model 1 (run 1): no focus offset. Kept as the negative control's numbers. */
    private val model1 = Optics.fromCalibration(Optics.CAM0_FX0, Optics.CAM0_D0, Optics.CAM0_SENSOR_MM / 1440)

    @Test
    fun model1FromCalibration() {
        assertTrue(rel(model1.focalMm, 4.40616) < 0.001)
        assertTrue(rel(Optics.fxPx(model1, 2.5)!!, 1136.5) < 1e-9)  // reproduces the calibration point
        assertTrue(rel(Optics.fxPx(model1, 10.0)!!, 1175.79) < 0.001)
        assertTrue(rel(Optics.umPerPx(model1, 10.0)!!, 85.049) < 0.001)
        assertTrue(rel(Optics.umPerPx(model1, 5.0)!!, 174.019) < 0.001)
    }

    @Test
    fun camera0WithFocusOffset() {
        // Model 2 (amendment after run 1): true focus = reported + 0.824 D, also at the calibration point.
        assertTrue(rel(cam0.focalMm, 4.39022) < 0.001)
        assertEquals(10.824, Optics.trueFocus(10.0)!!, 1e-9)
        assertTrue(rel(Optics.fxPx(cam0, Optics.trueFocus(2.5))!!, 1136.5) < 1e-9)
        assertTrue(rel(Optics.fxPx(cam0, Optics.trueFocus(10.0))!!, 1175.79) < 0.001)
        assertTrue(rel(Optics.umPerPx(cam0, Optics.trueFocus(10.0))!!, 78.575) < 0.001)
        assertTrue(rel(Optics.umPerPx(cam0, Optics.trueFocus(5.0))!!, 149.398) < 0.001)
        assertNull(Optics.trueFocus(null))
        assertNull(Optics.trueFocus(0.0))  // "infinity" or not reported: no correction, no scale
    }

    @Test
    fun negativeControlUncorrectedIsTenPercentOrMoreLarge() {
        for (d in doubleArrayOf(4.37, 5.57, 7.32)) {
            val e = Optics.umPerPx(model1, d)!! / Optics.umPerPx(cam0, Optics.trueFocus(d))!! - 1
            assertTrue("D=$d: $e", e > 0.10)
        }
    }

    @Test
    fun otherStreamWidthsScale() {
        val full = Optics.camera0(4032)
        assertTrue(rel(Optics.umPerPx(full, Optics.trueFocus(10.0))!! * 4032 / 1440, 78.575) < 0.001)
    }

    @Test
    fun invalidInputGivesNoScale() {
        assertNull(Optics.umPerPx(cam0, 0.0))
        assertNull(Optics.umPerPx(cam0, -1.0))
        assertNull(Optics.umPerPx(cam0, 228.0))  // beyond 1/f (227.8 D): no real image
        assertNull(Optics.umPerPx(cam0, Double.NaN))
        assertNull(Optics.umPerPx(cam0, null))
    }

    @Test
    fun negativeControlIgnoringBreathingFailsNearFrames() {
        val t = Optics.trueFocus(10.0)!!
        val noBreathing = 1e6 / (t * Optics.CAM0_FX0)
        assertEquals(0.0346, rel(noBreathing, Optics.umPerPx(cam0, t)!!), 0.001)
        assertTrue(rel(noBreathing, Optics.umPerPx(cam0, t)!!) > 0.02)
    }

    @Test
    fun negativeControlNominalLensFailsMedian() {
        // Model 2: nominal 4.30 mm at the corrected focus is 2.1 to 2.2 % off (hand calculation).
        val nominal = Optics.Lens(4.30, Optics.CAM0_SENSOR_MM / 1440)
        for (d in doubleArrayOf(10.0, 5.0, 2.5)) {
            val t = Optics.trueFocus(d)
            val e = rel(Optics.umPerPx(nominal, t)!!, Optics.umPerPx(cam0, t)!!)
            assertTrue("D=$d: $e", e in 0.019..0.024)
        }
    }

    @Test
    fun scaleBarPicksLargestRoundLengthThatFits() {
        // 85 µm/px at 10 cm: the largest of 0.5, 1, 2 and 5 mm that is at most maxPx long.
        assertEquals(5000.0, Optics.barUm(85.049, 400)!!.first, 0.0)  // 5 mm = 58.8 px
        assertEquals(1000.0, Optics.barUm(85.049, 15)!!.first, 0.0)   // 1 mm = 11.8 px
        assertEquals(58.79, Optics.barUm(85.049, 400)!!.second, 0.01)
        assertNull(Optics.barUm(85.049, 5))                            // even 0.5 mm (5.9 px) does not fit
        assertNull(Optics.barUm(null, 400))
    }
}
