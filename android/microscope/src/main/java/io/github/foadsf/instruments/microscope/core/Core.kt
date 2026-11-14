package io.github.foadsf.instruments.microscope.core

import java.nio.ByteBuffer

/** Pure value types shared by the core (no android.* here: the core is JVM-tested). */
data class Size2(val w: Int, val h: Int) {
    val area: Long get() = w.toLong() * h
}

/** Pixel rectangle; right and bottom are exclusive. */
data class Roi(val left: Int, val top: Int, val right: Int, val bottom: Int) {
    val width: Int get() = right - left
    val height: Int get() = bottom - top
}

/** One image plane as Android hands it over: rows [rowStride] apart, samples [pixelStride] apart. */
class PlaneView(val buf: ByteBuffer, val rowStride: Int, val pixelStride: Int)
