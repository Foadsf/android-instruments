package io.github.foadsf.instruments.microscope.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.exp
import kotlin.math.roundToInt

class SharpnessTest {
    private val w = 96
    private val h = 64

    private fun checkerboard(cell: Int = 4) = ByteArray(w * h) { i ->
        val x = i % w
        val y = i / w
        (if ((x / cell + y / cell) % 2 == 0) 40 else 215).toByte()
    }

    /** Separable Gaussian written here, independent of the code under test; edges clamp. */
    private fun blur(src: ByteArray, sigma: Double): ByteArray {
        val r = (3 * sigma).toInt().coerceAtLeast(1)
        val k = DoubleArray(2 * r + 1) { exp(-((it - r) * (it - r)) / (2 * sigma * sigma)) }
        val s = k.sum()
        for (i in k.indices) k[i] /= s
        val tmp = DoubleArray(w * h)
        for (y in 0 until h) for (x in 0 until w) {
            tmp[y * w + x] = k.indices.sumOf { j -> k[j] * (src[y * w + (x + j - r).coerceIn(0, w - 1)].toInt() and 0xff) }
        }
        return ByteArray(w * h) { i ->
            val x = i % w
            val y = i / w
            k.indices.sumOf { j -> k[j] * tmp[(y + j - r).coerceIn(0, h - 1) * w + x] }.roundToInt().toByte()
        }
    }

    private fun score(img: ByteArray) = Sharpness.meanSquaredLaplacian(img, w, Sharpness.centreHalf(w, h))

    @Test fun sharpScoresAboveBlurredStrictly() {
        val sharp = checkerboard()
        val s0 = score(sharp)
        val s1 = score(blur(sharp, 1.0))
        val s3 = score(blur(sharp, 3.0))
        assertTrue("$s0 > $s1 > $s3", s0 > s1 && s1 > s3)
        // negative control: the ordering test must fail when the inputs are swapped
        assertTrue(!(s3 > s1 && s1 > s0))
    }

    @Test fun flatImageScoresZero() = assertEquals(0.0, score(ByteArray(w * h) { 128.toByte() }), 0.0)

    @Test fun singleBrightPixelMatchesHandCalculation() {
        // one pixel of 10 in a 5x5 ROI of zeros: its Laplacian is 40, its four neighbours -10 each;
        // the 3x3 interior holds all five, so the mean square is (1600 + 4 * 100) / 9
        val img = ByteArray(w * h)
        img[2 * w + 2] = 10
        assertEquals(2000.0 / 9, Sharpness.meanSquaredLaplacian(img, w, Roi(0, 0, 5, 5)), 1e-9)
    }

    @Test fun strideIsRespected() {
        val stride = w + 13
        val padded = ByteArray(stride * h) { 255.toByte() } // padding would add edges if read
        val sharp = checkerboard()
        for (y in 0 until h) System.arraycopy(sharp, y * w, padded, y * stride, w)
        val roi = Sharpness.centreHalf(w, h)
        assertEquals(score(sharp), Sharpness.meanSquaredLaplacian(padded, stride, roi), 1e-9)
    }

    @Test fun centreHalfIsTheMiddle() = assertEquals(Roi(24, 16, 72, 48), Sharpness.centreHalf(w, h))
}
