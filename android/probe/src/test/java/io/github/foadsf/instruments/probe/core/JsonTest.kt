package io.github.foadsf.instruments.probe.core

import org.junit.Assert.assertEquals
import org.junit.Test

class JsonTest {
    @Test
    fun scalarsAndEscapes() {
        assertEquals("null", Json.write(null))
        assertEquals("true", Json.write(true))
        assertEquals("4.3", Json.write(4.3f))
        assertEquals("\"a\\\"b\\\\c\\nd\\u0001\"", Json.write("a\"b\\c\nd\u0001"))
    }

    @Test
    fun nonFiniteFloatsAreStringsBecauseJsonHasNoLiteral() {
        assertEquals("[\"NaN\",\"Infinity\",\"-Infinity\"]",
            Json.write(listOf(Float.NaN, Double.POSITIVE_INFINITY, Float.NEGATIVE_INFINITY), indent = 0))
    }

    /** Stands in for android.util.Rational, a Number whose toString() is "1/2" (seen on the Note8). */
    private class FractionNumber : Number() {
        override fun toDouble() = 0.5
        override fun toFloat() = 0.5f
        override fun toLong() = 0L
        override fun toInt() = 0
        override fun toShort(): Short = 0
        override fun toByte(): Byte = 0
        override fun toString() = "1/2"
    }

    @Test
    fun numberSubclassWithNonJsonTextIsQuoted() {
        assertEquals("[\"1/2\",-1.5E-7,42]", Json.write(listOf(FractionNumber(), -1.5e-7, 42L), indent = 0))
    }

    @Test
    fun compactNestedStructures() {
        val v = linkedMapOf("a" to intArrayOf(1, 2), "b" to listOf(mapOf("c" to null)), "e" to emptyMap<String, Any>())
        assertEquals("{\"a\":[1,2],\"b\":[{\"c\":null}],\"e\":{}}", Json.write(v, indent = 0))
    }

    @Test
    fun indentedOutputKeepsScalarArraysOnOneLine() {
        val v = linkedMapOf("size" to listOf(4032, 3024), "list" to listOf(listOf(1, 2)))
        val expected = "{\n  \"size\": [4032, 3024],\n  \"list\": [\n    [1, 2]\n  ]\n}"
        assertEquals(expected, Json.write(v))
    }

    @Test
    fun primitiveArraysOfEveryKind() {
        val v = listOf(longArrayOf(1), floatArrayOf(0.5f), doubleArrayOf(0.25), booleanArrayOf(false), byteArrayOf(7))
        assertEquals("[[1],[0.5],[0.25],[false],[7]]", Json.write(v, indent = 0))
    }
}
