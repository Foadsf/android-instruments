package io.github.foadsf.instruments.microscope.core

/**
 * Focus measure: the mean of the squared 4-neighbour Laplacian
 * L = 4 I(x,y) - I(x-1,y) - I(x+1,y) - I(x,y-1) - I(x,y+1)
 * over the interior of [roi] (pixels whose four neighbours are inside the ROI), in grey levels².
 * tools/microscope/live_checks.py computes the same number with NumPy as the cross-check.
 */
object Sharpness {
    fun meanSquaredLaplacian(luma: ByteArray, stride: Int, roi: Roi): Double {
        if (roi.width < 3 || roi.height < 3) return 0.0
        var sum = 0.0
        for (y in roi.top + 1 until roi.bottom - 1) {
            val row = y * stride
            for (x in roi.left + 1 until roi.right - 1) {
                val c = row + x
                val l = 4 * px(luma, c) - px(luma, c - 1) - px(luma, c + 1) - px(luma, c - stride) - px(luma, c + stride)
                sum += l.toDouble() * l
            }
        }
        return sum / ((roi.width - 2).toLong() * (roi.height - 2))
    }

    /** The middle half of a w x h frame in each direction. */
    fun centreHalf(w: Int, h: Int): Roi = Roi(w / 4, h / 4, w / 4 + w / 2, h / 4 + h / 2)

    private fun px(a: ByteArray, i: Int) = a[i].toInt() and 0xff
}
