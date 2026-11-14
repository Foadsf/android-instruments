package io.github.foadsf.instruments.microscope.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CameraChoiceTest {
    private val note8 = listOf("0", "1", "2")
    private val rear = setOf("0", "2")

    @Test fun requestedWinsWhenListed() = assertEquals("0", CameraChoice.pickCamera(note8, rear, "0"))

    @Test fun cameraTwoIsTheDefault() = assertEquals("2", CameraChoice.pickCamera(note8, rear, null))

    @Test fun unlistedRequestFallsBackToTheDefault() = assertEquals("2", CameraChoice.pickCamera(note8, rear, "7"))

    @Test fun withoutCameraTwoTheFirstRearCameraIsUsed() {
        // negative control: 2 is not listed, so 2 must never come back
        assertEquals("0", CameraChoice.pickCamera(listOf("1", "0"), setOf("0"), null))
        assertEquals("0", CameraChoice.pickCamera(listOf("1", "0"), setOf("0"), "2"))
    }

    @Test fun noRearCameraGivesNull() = assertNull(CameraChoice.pickCamera(listOf("1"), emptySet(), null))

    @Test fun fourThreeSizesComeFirstLargestFirstWithinTheCap() {
        val offered = listOf(Size2(4032, 3024), Size2(1920, 1080), Size2(1440, 1080), Size2(640, 480), Size2(1280, 720))
        assertEquals(
            listOf(Size2(1440, 1080), Size2(640, 480), Size2(1920, 1080), Size2(1280, 720)),
            CameraChoice.sizeCandidates(offered),
        )
    }

    @Test fun nothingWithinTheCapGivesAnEmptyList() =
        assertEquals(emptyList<Size2>(), CameraChoice.sizeCandidates(listOf(Size2(4032, 3024))))
}
