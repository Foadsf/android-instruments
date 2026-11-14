package io.github.foadsf.instruments.microscope.core

import org.junit.Assert.assertEquals
import org.junit.Test
import kotlin.random.Random

class FrameRateTest {
    @Test fun thirtyFpsWithJitterReadsThirty() {
        val r = FrameRate()
        val rnd = Random(7)
        val period = 1_000_000_000L / 30
        for (i in 0 until 120) r.add(i * period + rnd.nextLong(-2_000_000L, 2_000_000L))
        assertEquals(30.0, r.fps(2_000_000_000L), 0.3)
    }

    @Test fun onlyTheWindowCounts() {
        val r = FrameRate()
        for (i in 0 until 30) r.add(i * 100_000_000L) // 10 fps for 3 s
        for (i in 1..60) r.add(2_900_000_000L + i * 33_333_333L) // then 30 fps for 2 s
        assertEquals(30.0, r.fps(1_500_000_000L), 0.3)
    }

    @Test fun fewerThanTwoFramesIsZero() {
        val r = FrameRate()
        assertEquals(0.0, r.fps(1_000_000_000L), 0.0)
        r.add(5L)
        assertEquals(0.0, r.fps(1_000_000_000L), 0.0)
    }
}
