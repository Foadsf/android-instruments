package io.github.foadsf.instruments.probe.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EventLogTest {
    private val lines = mutableListOf<String>()
    private fun log(min: Level, ring: Int = 3) = EventLog("run1", min, { _, l -> lines += l }, { "T" }, ring)

    @Test
    fun lineIsCompactJsonWithFixedHeadFields() {
        log(Level.INFO).info("camera.listed") { mapOf("ids" to listOf("0", "1"), "event" to "ignored") }
        assertEquals(listOf("{\"ts\":\"T\",\"level\":\"INFO\",\"run_id\":\"run1\",\"event\":\"camera.listed\",\"ids\":[\"0\",\"1\"]}"), lines)
    }

    @Test
    fun debugIsSilentAtInfoButReplayedBeforeAnError() {
        val l = log(Level.INFO, ring = 2)
        l.debug("d1")
        l.debug("d2")
        l.debug("d3")
        assertTrue(lines.isEmpty())
        l.error("boom")
        val events = lines.map { Regex("\"event\":\"([^\"]+)\"").find(it)!!.groupValues[1] }
        assertEquals(listOf("log.ring_replay", "d2", "d3", "boom"), events)
    }

    @Test
    fun ringIsEmptiedAfterReplay() {
        val l = log(Level.INFO)
        l.debug("d1")
        l.error("e1")
        l.error("e2")
        // replay marker, d1, e1, e2: the second error must not replay d1 again.
        assertEquals(4, lines.size)
        assertEquals(1, lines.count { it.contains("\"event\":\"log.ring_replay\"") })
    }

    @Test
    fun traceFieldsAreNotBuiltWhenTraceIsOff() {
        var built = false
        log(Level.DEBUG).trace("t") { built = true; emptyMap() }
        assertFalse(built)
        assertTrue(lines.isEmpty())
    }

    @Test
    fun debugIsWrittenDirectlyWhenVerbose() {
        log(Level.DEBUG).debug("d1")
        assertEquals(1, lines.size)
    }
}
