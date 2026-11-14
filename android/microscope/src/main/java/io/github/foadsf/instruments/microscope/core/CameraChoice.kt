package io.github.foadsf.instruments.microscope.core

/** Which camera and which stream size the app asks for. */
object CameraChoice {
    /** On the Note8 with the shim, camera 2 is the telephoto (docs/units/camera-bridge.md). */
    const val DEFAULT_ID = "2"

    /** [requested] if listed; else [DEFAULT_ID] if listed; else the first rear camera; else null. */
    fun pickCamera(listed: List<String>, rear: Set<String>, requested: String?): String? = when {
        requested != null && requested in listed -> requested
        DEFAULT_ID in listed -> DEFAULT_ID
        else -> listed.firstOrNull { it in rear }
    }

    /**
     * Sizes worth trying, best first: 4:3 sizes (the sensor's full field) largest first, then the
     * others largest first, all within [maxPixels]. The camera 2 bridge only accepts HAL1 preview
     * sizes, so the caller walks down this list until a session configures.
     */
    fun sizeCandidates(sizes: List<Size2>, maxPixels: Long = 1920L * 1440): List<Size2> {
        val fit = sizes.filter { it.area <= maxPixels }.distinct().sortedByDescending { it.area }
        val (fourThree, other) = fit.partition { it.w * 3 == it.h * 4 }
        return fourThree + other
    }
}
