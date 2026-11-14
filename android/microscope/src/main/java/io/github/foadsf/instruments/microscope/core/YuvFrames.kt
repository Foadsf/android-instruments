package io.github.foadsf.instruments.microscope.core

/** YUV_420_888 frames: packing to I420, the digital-zoom crop, and the downsampled colour preview. */
object YuvFrames {
    /**
     * Copies three planes with any row and pixel stride into packed I420 (Y, then U, then V, no
     * padding). Reads only the samples, so a last row cut short after its final sample is fine.
     */
    fun packI420(y: PlaneView, u: PlaneView, v: PlaneView, w: Int, h: Int, out: ByteArray = ByteArray(w * h * 3 / 2)): ByteArray {
        require(w > 0 && h > 0 && w % 2 == 0 && h % 2 == 0) { "I420 needs even, positive sizes: ${w}x$h" }
        require(out.size >= w * h * 3 / 2) { "output too small" }
        copyPlane(y, w, h, out, 0)
        copyPlane(u, w / 2, h / 2, out, w * h)
        copyPlane(v, w / 2, h / 2, out, w * h + w * h / 4)
        return out
    }

    /** Row-wise bulk reads: one ByteBuffer.get(ByteArray) per row, never one call per sample. */
    private fun copyPlane(p: PlaneView, w: Int, h: Int, out: ByteArray, offset: Int) {
        val src = p.buf.duplicate()
        val span = (w - 1) * p.pixelStride + 1
        val row = if (p.pixelStride == 1) null else ByteArray(span)
        var o = offset
        for (y in 0 until h) {
            src.position(y * p.rowStride)
            if (row == null) {
                src.get(out, o, w)
                o += w
            } else {
                src.get(row, 0, span)
                for (x in 0 until w) out[o++] = row[x * p.pixelStride]
            }
        }
    }

    /** The centred w/zoom x h/zoom rectangle, with even corners so chroma stays aligned. */
    fun cropForZoom(w: Int, h: Int, zoom: Int): Roi {
        require(zoom >= 1) { "zoom must be >= 1: $zoom" }
        val cw = (w / zoom) and 1.inv()
        val ch = (h / zoom) and 1.inv()
        val left = ((w - cw) / 2) and 1.inv()
        val top = ((h - ch) / 2) and 1.inv()
        return Roi(left, top, left + cw, top + ch)
    }

    /**
     * Nearest-neighbour samples [crop] of a packed I420 frame into [out] (outW x outH ARGB),
     * full-range BT.601 (JFIF), the range camera YUV_420_888 uses.
     */
    fun previewArgb(i420: ByteArray, w: Int, h: Int, crop: Roi, outW: Int, outH: Int, out: IntArray) {
        require(out.size >= outW * outH) { "output too small" }
        val uBase = w * h
        val vBase = uBase + w * h / 4
        val cw = crop.width
        val xs = IntArray(outW) { crop.left + it * cw / outW } // source column per output column
        var o = 0
        for (oy in 0 until outH) {
            val sy = crop.top + oy * crop.height / outH
            val yRow = sy * w
            val cRow = (sy shr 1) * (w shr 1)
            for (ox in 0 until outW) {
                val sx = xs[ox]
                val yv = i420[yRow + sx].toInt() and 0xff
                val ci = cRow + (sx shr 1)
                val cb = (i420[uBase + ci].toInt() and 0xff) - 128
                val cr = (i420[vBase + ci].toInt() and 0xff) - 128
                // 16.16 fixed point of 1.402, 0.344136, 0.714136, 1.772
                val r = clamp(yv + ((91881 * cr + HALF) shr 16))
                val g = clamp(yv - ((22554 * cb + 46802 * cr + HALF) shr 16))
                val b = clamp(yv + ((116130 * cb + HALF) shr 16))
                out[o++] = (0xff shl 24) or (r shl 16) or (g shl 8) or b
            }
        }
    }

    private const val HALF = 1 shl 15

    private fun clamp(v: Int): Int = if (v < 0) 0 else if (v > 255) 255 else v
}
