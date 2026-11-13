package io.github.foadsf.instruments.probe.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TrialPlannerTest {
    private val note10Sizes = setOf(Size2(4032, 3024), Size2(1920, 1080), Size2(1440, 1080), Size2(1280, 960), Size2(640, 480))

    @Test
    fun chooseSizesPicksFourThreeFullHdAndLargest() {
        assertEquals(listOf(Size2(1440, 1080), Size2(1920, 1080), Size2(4032, 3024)), TrialPlanner.chooseSizes(note10Sizes))
    }

    @Test
    fun chooseSizesDropsDuplicatesAndHandlesEmpty() {
        assertEquals(listOf(Size2(1280, 960)), TrialPlanner.chooseSizes(setOf(Size2(1280, 960))))
        assertEquals(emptyList<Size2>(), TrialPlanner.chooseSizes(emptySet()))
    }

    @Test
    fun standaloneCamerasGetOnlyAControl() {
        // Note8 on LineageOS 20: two standalone cameras, no logical multi-camera.
        val cams = listOf(
            CameraInfo("0", false, emptyList(), note10Sizes),
            CameraInfo("1", false, emptyList(), setOf(Size2(1280, 960))),
        )
        val plans = TrialPlanner.plan(cams)
        assertEquals(listOf("0", "1"), plans.map { it.openId })
        assertTrue(plans.all { it.kind == TrialKind.CONTROL && it.streams.single().physicalId == null })
    }

    @Test
    fun logicalCameraGetsControlSinglesAndPairsButPhysicalsAreNotOpenedAlone() {
        // Note10 logical 20 = {0, 52, 2}; physical 52 publishes no stream map of its own.
        val cams = listOf(
            CameraInfo("20", true, listOf("0", "2", "52"), note10Sizes),
            CameraInfo("0", false, emptyList(), note10Sizes),
            CameraInfo("2", false, emptyList(), setOf(Size2(1440, 1080), Size2(4608, 3456))),
            CameraInfo("52", false, emptyList(), emptySet()),
        )
        val plans = TrialPlanner.plan(cams)
        assertTrue(plans.all { it.openId == "20" })
        assertEquals(1, plans.count { it.kind == TrialKind.CONTROL })
        assertEquals(listOf("0", "2", "52"), plans.filter { it.kind == TrialKind.PHYSICAL_SINGLE }.map { it.streams[0].physicalId })
        val pairs = plans.filter { it.kind == TrialKind.PHYSICAL_PAIR }.map { it.label }
        assertEquals(listOf(
            "20:0@1440x1080+2@1440x1080",
            "20:0@1440x1080+52@1440x1080", "20:0@1920x1080+52@1920x1080", "20:0@4032x3024+52@4032x3024",
            "20:2@1440x1080+52@1440x1080",
        ), pairs)
    }

    @Test
    fun planIsCapped() {
        val many = (0 until 60).map { CameraInfo("$it", false, emptyList(), note10Sizes) }
        assertEquals(TrialPlanner.MAX_TRIALS, TrialPlanner.plan(many).size)
    }
}
