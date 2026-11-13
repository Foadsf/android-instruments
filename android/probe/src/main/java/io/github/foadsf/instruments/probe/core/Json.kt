package io.github.foadsf.instruments.probe.core

/**
 * Minimal JSON writer for probe reports and log lines; no Android dependency so it runs in JVM
 * tests. Accepts null, Boolean, Number, String, Map<String, *>, Iterable<*> and primitive or
 * object arrays. Non-finite floating-point values become the strings "NaN", "Infinity" and
 * "-Infinity", because JSON has no literal for them. Anything else is written as its toString().
 */
object Json {
    /**
     * RFC 8259 number grammar. A Number subclass whose text does not match (android.util.Rational
     * prints "1/2") is written as a string, so the output is always valid JSON.
     */
    private val JSON_NUMBER = Regex("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?")

    /** [indent] 0 writes one compact line; otherwise nested containers are indented. */
    fun write(value: Any?, indent: Int = 2): String = StringBuilder().also { append(it, value, indent, 0) }.toString()

    private fun append(sb: StringBuilder, v: Any?, indent: Int, depth: Int) {
        when (v) {
            null -> sb.append("null")
            is Boolean -> sb.append(v)
            is Float -> number(sb, v.toDouble(), v.toString())
            is Double -> number(sb, v, v.toString())
            is Number -> v.toString().let { if (JSON_NUMBER.matches(it)) sb.append(it) else string(sb, it) }
            is CharSequence -> string(sb, v.toString())
            is Map<*, *> -> obj(sb, v, indent, depth)
            is Iterable<*> -> arr(sb, v.toList(), indent, depth)
            is Array<*> -> arr(sb, v.toList(), indent, depth)
            is IntArray -> arr(sb, v.toList(), indent, depth)
            is LongArray -> arr(sb, v.toList(), indent, depth)
            is FloatArray -> arr(sb, v.toList(), indent, depth)
            is DoubleArray -> arr(sb, v.toList(), indent, depth)
            is BooleanArray -> arr(sb, v.toList(), indent, depth)
            is ByteArray -> arr(sb, v.toList(), indent, depth)
            else -> string(sb, v.toString())
        }
    }

    private fun number(sb: StringBuilder, d: Double, text: String) {
        when {
            d.isNaN() -> sb.append("\"NaN\"")
            d.isInfinite() -> sb.append(if (d > 0) "\"Infinity\"" else "\"-Infinity\"")
            else -> sb.append(text)
        }
    }

    fun escape(s: String): String = buildString {
        for (c in s) {
            when (c) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> if (c < ' ') append("\\u%04x".format(c.code)) else append(c)
            }
        }
    }

    private fun string(sb: StringBuilder, s: String) {
        sb.append('"').append(escape(s)).append('"')
    }

    private fun isScalar(v: Any?) = v == null || v is Boolean || v is Number || v is CharSequence

    private fun newline(sb: StringBuilder, indent: Int, depth: Int) {
        if (indent > 0) sb.append('\n').append(" ".repeat(indent * depth))
    }

    private fun obj(sb: StringBuilder, m: Map<*, *>, indent: Int, depth: Int) {
        if (m.isEmpty()) {
            sb.append("{}")
            return
        }
        sb.append('{')
        m.entries.forEachIndexed { i, (k, v) ->
            if (i > 0) sb.append(',')
            newline(sb, indent, depth + 1)
            string(sb, k.toString())
            sb.append(if (indent > 0) ": " else ":")
            append(sb, v, indent, depth + 1)
        }
        newline(sb, indent, depth)
        sb.append('}')
    }

    /** Arrays of scalars stay on one line, which keeps size and calibration arrays readable. */
    private fun arr(sb: StringBuilder, items: List<Any?>, indent: Int, depth: Int) {
        val flat = items.all(::isScalar)
        sb.append('[')
        items.forEachIndexed { i, v ->
            if (i > 0) sb.append(if (flat && indent > 0) ", " else ",")
            if (!flat) newline(sb, indent, depth + 1)
            append(sb, v, indent, depth + 1)
        }
        if (!flat && items.isNotEmpty()) newline(sb, indent, depth)
        sb.append(']')
    }
}
