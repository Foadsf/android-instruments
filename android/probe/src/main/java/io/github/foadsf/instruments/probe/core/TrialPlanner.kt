package io.github.foadsf.instruments.probe.core

data class Size2(val w: Int, val h: Int) {
    val area: Long get() = w.toLong() * h
}

/** What the planner needs to know about one camera ID (logical, physical or standalone). */
data class CameraInfo(
    val id: String,
    val isLogicalMulti: Boolean,
    val physicalIds: List<String>,
    /** YUV_420_888 output sizes this ID publishes; empty when it publishes no stream map. */
    val yuvSizes: Set<Size2>,
)

enum class TrialKind {
    /**
     * One stream on a camera ID itself, with no physical routing: the positive control that
     * proves the trial machinery and that camera work before anything harder is judged.
     */
    CONTROL,

    /** One stream routed to one physical camera: proves physical routing works at all. */
    PHYSICAL_SINGLE,

    /** Two streams routed to two physical cameras in one session: the Gate 1 question. */
    PHYSICAL_PAIR,
}

data class StreamSpec(val physicalId: String?, val size: Size2)

data class TrialPlan(val openId: String, val kind: TrialKind, val streams: List<StreamSpec>) {
    val label: String
        get() = "$openId:" + streams.joinToString("+") { "${it.physicalId ?: "logical"}@${it.size.w}x${it.size.h}" }
}

/** Decides which stream combinations the probe tries. Pure: tested on the JVM. */
object TrialPlanner {
    const val MAX_TRIALS = 40

    /**
     * Up to three sizes, smallest first: the largest 4:3 size within 1440x1080, 1920x1080 when
     * available, and the largest size. Duplicates are dropped.
     */
    fun chooseSizes(available: Set<Size2>): List<Size2> {
        val fourThree = available.filter { it.w * 3 == it.h * 4 && it.w <= 1440 && it.h <= 1080 }.maxByOrNull { it.area }
        val fullHd = Size2(1920, 1080).takeIf { it in available }
        val largest = available.maxByOrNull { it.area }
        return listOfNotNull(fourThree, fullHd, largest).distinct()
    }

    /** Logical multi-cameras get control, single and pair trials; standalone cameras a control. */
    fun plan(cameras: List<CameraInfo>): List<TrialPlan> {
        val byId = cameras.associateBy { it.id }
        val logical = cameras.filter { it.isLogicalMulti && it.physicalIds.size >= 2 }
        val physical = logical.flatMap { it.physicalIds }.toSet()
        val standalone = cameras.filter { it !in logical && it.id !in physical }
        val controls = standalone.mapNotNull { cam ->
            chooseSizes(cam.yuvSizes).firstOrNull()?.let { TrialPlan(cam.id, TrialKind.CONTROL, listOf(StreamSpec(null, it))) }
        }
        return (controls + logical.flatMap { planLogical(it, byId) }).take(MAX_TRIALS)
    }

    private fun planLogical(logical: CameraInfo, byId: Map<String, CameraInfo>): List<TrialPlan> {
        // A physical camera that publishes no stream map follows the logical camera's map.
        fun sizesOf(id: String) = byId[id]?.yuvSizes?.takeIf { it.isNotEmpty() } ?: logical.yuvSizes
        val out = mutableListOf<TrialPlan>()
        chooseSizes(logical.yuvSizes).firstOrNull()?.let {
            out += TrialPlan(logical.id, TrialKind.CONTROL, listOf(StreamSpec(null, it)))
        }
        for (p in logical.physicalIds) {
            chooseSizes(sizesOf(p)).firstOrNull()?.let {
                out += TrialPlan(logical.id, TrialKind.PHYSICAL_SINGLE, listOf(StreamSpec(p, it)))
            }
        }
        val ids = logical.physicalIds
        for (i in ids.indices) for (j in i + 1 until ids.size) {
            for (s in chooseSizes(sizesOf(ids[i]) intersect sizesOf(ids[j]))) {
                out += TrialPlan(logical.id, TrialKind.PHYSICAL_PAIR, listOf(StreamSpec(ids[i], s), StreamSpec(ids[j], s)))
            }
        }
        return out
    }
}
