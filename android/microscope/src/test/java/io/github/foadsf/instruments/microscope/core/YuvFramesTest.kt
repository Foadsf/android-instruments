package io.github.foadsf.instruments.microscope.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.nio.ByteBuffer

class YuvFramesTest {
    /** A plane like Android's: rows padded to [rowStride], last row cut after its last sample. */
    private fun plane(w: Int, h: Int, rowStride: Int, pixelStride: Int, value: (Int, Int) -> Int): PlaneView {
        val size = rowStride * (h - 1) + (w - 1) * pixelStride + 1
        val bytes = ByteArray(size) { 0x5a } // filler that must never be copied
        for (y in 0 until h) for (x in 0 until w) bytes[y * rowStride + x * pixelStride] = value(x, y).toByte()
        return PlaneView(ByteBuffer.wrap(bytes), rowStride, pixelStride)
    }

    @Test fun oddStridesPackToExactI420() {
        val w = 6
        val h = 4
        val y = plane(w, h, 11, 1) { x, yy -> 10 * yy + x }
        val u = plane(w / 2, h / 2, 9, 2) { x, yy -> 100 + 10 * yy + x }
        val v = plane(w / 2, h / 2, 9, 2) { x, yy -> 200 + 10 * yy + x }
        val expected = ByteArray(w * h * 3 / 2)
        var i = 0
        for (yy in 0 until h) for (x in 0 until w) expected[i++] = (10 * yy + x).toByte()
        for (yy in 0 until h / 2) for (x in 0 until w / 2) expected[i++] = (100 + 10 * yy + x).toByte()
        for (yy in 0 until h / 2) for (x in 0 until w / 2) expected[i++] = (200 + 10 * yy + x).toByte()
        assertArrayEquals(expected, YuvFrames.packI420(y, u, v, w, h))
    }

    @Test fun oddSizesAreRefused() {
        val p = plane(5, 4, 5, 1) { _, _ -> 0 }
        assertThrows(IllegalArgumentException::class.java) { YuvFrames.packI420(p, p, p, 5, 4) }
    }

    @Test fun zoomCropIsCentredAndEven() {
        assertEquals(Roi(360, 270, 1080, 810), YuvFrames.cropForZoom(1440, 1080, 2))
        assertEquals(Roi(0, 0, 1440, 1080), YuvFrames.cropForZoom(1440, 1080, 1))
        val odd = YuvFrames.cropForZoom(1442, 1082, 4)
        listOf(odd.left, odd.top, odd.right, odd.bottom).forEach { assertEquals(0, it % 2) }
        assertThrows(IllegalArgumentException::class.java) { YuvFrames.cropForZoom(1440, 1080, 0) }
    }

    private fun i420(w: Int, h: Int, y: Int, u: Int, v: Int) = ByteArray(w * h * 3 / 2).also {
        it.fill(y.toByte(), 0, w * h)
        it.fill(u.toByte(), w * h, w * h * 5 / 4)
        it.fill(v.toByte(), w * h * 5 / 4, w * h * 3 / 2)
    }

    private fun rgb(argb: Int) = Triple(argb shr 16 and 0xff, argb shr 8 and 0xff, argb and 0xff)

    @Test fun fullRangeBt601ColoursConvert() {
        val out = IntArray(4)
        YuvFrames.previewArgb(i420(4, 4, 128, 128, 128), 4, 4, Roi(0, 0, 4, 4), 2, 2, out)
        assertEquals(Triple(128, 128, 128), rgb(out[0]))
        // JPEG/JFIF red: Y 76.245, Cb 84.972, Cr 255.5
        YuvFrames.previewArgb(i420(4, 4, 76, 85, 255), 4, 4, Roi(0, 0, 4, 4), 2, 2, out)
        val (r, g, b) = rgb(out[0])
        assertEquals(255.0, r.toDouble(), 2.0)
        assertEquals(0.0, g.toDouble(), 2.0)
        assertEquals(0.0, b.toDouble(), 2.0)
        assertEquals(0xff, out[0] ushr 24)
    }

    @Test fun previewSamplesTheCrop() {
        val w = 8
        val h = 8
        val frame = i420(w, h, 0, 128, 128)
        for (yy in 0 until h) for (x in 0 until w) frame[yy * w + x] = (x * 10 + yy).toByte() // grey ramp
        val out = IntArray(4)
        YuvFrames.previewArgb(frame, w, h, Roi(4, 2, 8, 6), 2, 2, out) // 4x4 crop to 2x2: picks x 4,6 and y 2,4
        assertEquals(listOf(42, 62, 44, 64), out.map { rgb(it).first })
    }
}
