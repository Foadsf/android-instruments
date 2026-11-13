package io.github.foadsf.instruments.probe.core

enum class Level { TRACE, DEBUG, INFO, WARN, ERROR }

/**
 * Structured event log: one compact JSON object per line with a timestamp, level, run id, event
 * name and fields. Lines below [minLevel] are not written, but the most recent [ringSize] DEBUG
 * lines are kept in memory and written just before the next ERROR, so a failure arrives with its
 * own trail even when verbose logging was off. TRACE lines are never kept; their fields are built
 * lazily and only when TRACE is enabled.
 */
class EventLog(
    private val runId: String,
    private val minLevel: Level,
    private val sink: (Level, String) -> Unit,
    private val clock: () -> String,
    private val ringSize: Int = 200,
) {
    private val ring = ArrayDeque<String>()

    fun trace(event: String, fields: () -> Map<String, Any?> = { emptyMap() }) = log(Level.TRACE, event, fields)
    fun debug(event: String, fields: () -> Map<String, Any?> = { emptyMap() }) = log(Level.DEBUG, event, fields)
    fun info(event: String, fields: () -> Map<String, Any?> = { emptyMap() }) = log(Level.INFO, event, fields)
    fun warn(event: String, fields: () -> Map<String, Any?> = { emptyMap() }) = log(Level.WARN, event, fields)
    fun error(event: String, fields: () -> Map<String, Any?> = { emptyMap() }) = log(Level.ERROR, event, fields)

    @Synchronized
    fun log(level: Level, event: String, fields: () -> Map<String, Any?>) {
        val enabled = level >= minLevel
        if (!enabled && level != Level.DEBUG) return
        val line = format(level, event, fields())
        if (!enabled) {
            remember(line)
            return
        }
        if (level == Level.ERROR && ring.isNotEmpty()) flushRing()
        sink(level, line)
    }

    private fun format(level: Level, event: String, fields: Map<String, Any?>): String {
        val head = linkedMapOf<String, Any?>("ts" to clock(), "level" to level.name, "run_id" to runId, "event" to event)
        for ((k, v) in fields) if (k !in head) head[k] = v
        return Json.write(head, indent = 0)
    }

    private fun remember(line: String) {
        if (ring.size == ringSize) ring.removeFirst()
        ring.addLast(line)
    }

    private fun flushRing() {
        sink(Level.WARN, format(Level.WARN, "log.ring_replay", mapOf("lines" to ring.size)))
        while (ring.isNotEmpty()) sink(Level.DEBUG, ring.removeFirst())
    }
}
