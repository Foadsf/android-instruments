package io.github.foadsf.instruments.microscope.core

/**
 * Hand-held calibration (camera-calibration.md, hand-held amendment): a frame is kept only if the
 * gyroscope stayed below [rateRadS] for the whole time the sensor saw it, from the start of the
 * first row's exposure to the end of the last row's ([exposureNs] + rolling-shutter [readoutNs]),
 * widened by [padNs] for clock jitter, and at least [minGapNs] after the last kept frame. Fewer
 * than [minSamples] gyroscope samples in that window cannot show calm, so the frame is refused.
 */
class FrameGate(val rateRadS: Double, val minGapNs: Long, val padNs: Long, val minSamples: Int) {
    data class Rate(val tsNs: Long, val radS: Double)
    data class Decision(val keep: Boolean, val reason: String, val maxRate: Double, val samples: Int)

    companion object {
        /** "0:0.04,2:0.02" -> {0: 0.04, 2: 0.02}, the gyro limit per camera; throws on anything else. */
        fun parseGates(text: String): Map<String, Double> {
            val out = LinkedHashMap<String, Double>()
            for (part in text.split(',')) {
                val (cam, value) = part.split(':').let { require(it.size == 2) { "gate '$part': want CAMERA:RAD_S" }; it[0].trim() to it[1] }
                val rate = requireNotNull(value.trim().toDoubleOrNull()) { "gate '$part': not a number" }
                require(cam.isNotEmpty() && rate > 0 && cam !in out) { "gate '$part': positive rate, each camera once" }
                out[cam] = rate
            }
            return out
        }
    }

    fun window(startNs: Long, exposureNs: Long, readoutNs: Long): LongRange =
        (startNs - padNs)..(startNs + exposureNs + readoutNs + padNs)

    fun decide(startNs: Long, exposureNs: Long, readoutNs: Long, gyro: List<Rate>, lastKeptNs: Long?): Decision {
        if (lastKeptNs != null && startNs - lastKeptNs < minGapNs) return Decision(false, "gap", Double.NaN, 0)
        val w = window(startNs, exposureNs, readoutNs)
        val inside = gyro.filter { it.tsNs in w }
        if (inside.size < minSamples) return Decision(false, "samples ${inside.size}", Double.NaN, inside.size)
        val max = inside.maxOf { it.radS }
        return if (max < rateRadS) Decision(true, "ok", max, inside.size)
        else Decision(false, String.format(java.util.Locale.ROOT, "gyro %.4f rad/s", max), max, inside.size)
    }
}
