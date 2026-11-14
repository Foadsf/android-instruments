package io.github.foadsf.instruments.microscope.core

/** Frame rate from sensor timestamps (ns) over a sliding window. Not thread-safe: one caller. */
class FrameRate(private val capacity: Int = 512) {
    private val ts = LongArray(capacity)
    private var head = 0
    private var size = 0

    fun add(tsNs: Long) {
        ts[(head + size) % capacity] = tsNs
        if (size < capacity) size++ else head = (head + 1) % capacity
    }

    /** Frames per second among the frames within [windowNs] of the newest; 0 with fewer than two. */
    fun fps(windowNs: Long): Double {
        if (size < 2) return 0.0
        val newest = ts[(head + size - 1) % capacity]
        var n = 1
        var oldest = newest
        for (i in size - 2 downTo 0) {
            val t = ts[(head + i) % capacity]
            if (newest - t > windowNs) break
            oldest = t
            n++
        }
        return if (n < 2 || newest == oldest) 0.0 else (n - 1) * 1e9 / (newest - oldest)
    }
}
