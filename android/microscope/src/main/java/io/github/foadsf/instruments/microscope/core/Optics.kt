package io.github.foadsf.instruments.microscope.core

/**
 * Scale on the plane in focus (microscope-scale.md): a thin lens whose focal length is fitted to
 * the camera calibration, so focus breathing follows from the reported focus distance. Distances
 * in mm, focus in diopters (1/m). Invalid input gives null, never a guess.
 */
object Optics {
    /** [focalMm]: focal length; [pitchMm]: the size of one pixel of the stream on the sensor. */
    data class Lens(val focalMm: Double, val pitchMm: Double)

    /** Camera 0 (Note8 wide) calibration: fx at the 1440 px stream, at the series' fixed focus. */
    const val CAM0_FX0 = 1136.5
    const val CAM0_D0 = 2.5
    const val CAM0_SENSOR_MM = 5.645
    const val CAM0_WIDTH = 1440
    val CAM0_RUNS = listOf("20261115_155558-d0aa", "20261115_163037-f2e7")
    const val MODEL = "thin-lens-breathing-1"

    /** Thin lens through one calibration point: 1/f = 1/v0 + D0, with v0 = fx0 x pitch. */
    fun fromCalibration(fx0Px: Double, d0Diopters: Double, pitchMm: Double): Lens {
        val v0 = fx0Px * pitchMm
        return Lens(1.0 / (1.0 / v0 + d0Diopters / 1000.0), pitchMm)
    }

    /** Camera 0 for a stream [width] px wide (the calibration was at 1440 px). */
    fun camera0(width: Int = CAM0_WIDTH): Lens =
        fromCalibration(CAM0_FX0 * width / CAM0_WIDTH, CAM0_D0, CAM0_SENSOR_MM / width)

    /** Image distance v(D) = 1 / (1/f - D), or null when D is not a finite focus in (0, 1/f). */
    fun imageDistanceMm(lens: Lens, diopters: Double?): Double? {
        if (diopters == null || !diopters.isFinite() || diopters <= 0.0) return null
        val inv = 1.0 / lens.focalMm - diopters / 1000.0
        return if (inv <= 0.0) null else 1.0 / inv
    }

    /** Focal length in pixels at focus D. */
    fun fxPx(lens: Lens, diopters: Double?): Double? = imageDistanceMm(lens, diopters)?.let { it / lens.pitchMm }

    /** µm on the plane in focus per stream pixel: object distance (1000/D mm) over fx(D). */
    fun umPerPx(lens: Lens, diopters: Double?): Double? =
        fxPx(lens, diopters)?.let { fx -> 1e6 / (diopters!! * fx) }

    /** The largest of 0.5, 1, 2 and 5 mm that is at most [maxPx] long: (length µm, length px). */
    fun barUm(umPerPx: Double?, maxPx: Int): Pair<Double, Double>? {
        if (umPerPx == null || !umPerPx.isFinite() || umPerPx <= 0.0) return null
        return BARS_UM.reversed().firstOrNull { it / umPerPx <= maxPx }?.let { it to it / umPerPx }
    }

    private val BARS_UM = listOf(500.0, 1000.0, 2000.0, 5000.0)
}
