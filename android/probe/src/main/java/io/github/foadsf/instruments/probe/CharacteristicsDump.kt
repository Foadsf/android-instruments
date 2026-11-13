package io.github.foadsf.instruments.probe

import android.graphics.ImageFormat
import android.graphics.Rect
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.params.StreamConfigurationMap
import android.util.Range
import android.util.Rational
import android.util.Size
import android.util.SizeF
import io.github.foadsf.instruments.probe.core.Size2

/**
 * Every public CameraCharacteristics key, converted to JSON-ready values. Key names are the
 * framework's own (`android.lens.facing`), which are also the tag names `dumpsys media.camera`
 * prints, so the two can be compared field by field.
 *
 * Conventions (docs/units/device-probe.md): Size and SizeF -> [w, h]; Rect -> [left, top, width,
 * height], as dumpsys prints active-array rectangles; Range -> [lower, upper]; Rational ->
 * [numerator, denominator]; enums stay integers; unknown types -> toString().
 */
object CharacteristicsDump {
    fun toMap(c: CameraCharacteristics): Map<String, Any?> =
        c.keys.associate { key ->
            key.name to runCatching { convert(c.get(key)) }.getOrElse { "error: ${it.javaClass.simpleName}" }
        }.toSortedMap()

    fun convert(v: Any?): Any? = when (v) {
        null -> null
        // Rational extends Number, so it must be matched before the Number branch.
        is Rational -> listOf(v.numerator, v.denominator)
        is Boolean, is Number, is String -> v
        is Size -> listOf(v.width, v.height)
        is SizeF -> listOf(v.width, v.height)
        is Rect -> listOf(v.left, v.top, v.width(), v.height())
        is Range<*> -> listOf(convert(v.lower), convert(v.upper))
        is StreamConfigurationMap -> streamMap(v)
        is IntArray -> v.toList()
        is LongArray -> v.toList()
        is FloatArray -> v.toList()
        is DoubleArray -> v.toList()
        is BooleanArray -> v.toList()
        is ByteArray -> v.toList()
        is Array<*> -> v.map(::convert)
        else -> v.toString()
    }

    fun yuvSizes(c: CameraCharacteristics): Set<Size2> =
        c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?.getOutputSizes(ImageFormat.YUV_420_888)
            ?.map { Size2(it.width, it.height) }?.toSet().orEmpty()

    private fun streamMap(m: StreamConfigurationMap): Map<String, Any?> {
        val formats = m.outputFormats.toList()
        return linkedMapOf(
            "output_sizes" to formats.associate { f ->
                formatName(f) to m.getOutputSizes(f)?.map { listOf(it.width, it.height) }
            },
            "high_resolution_output_sizes" to formats.associate { f ->
                formatName(f) to m.getHighResolutionOutputSizes(f)?.map { listOf(it.width, it.height) }
            }.filterValues { !it.isNullOrEmpty() },
        )
    }

    private fun formatName(f: Int): String = when (f) {
        ImageFormat.YUV_420_888 -> "YUV_420_888"
        ImageFormat.JPEG -> "JPEG"
        ImageFormat.RAW_SENSOR -> "RAW_SENSOR"
        ImageFormat.RAW10 -> "RAW10"
        ImageFormat.RAW12 -> "RAW12"
        ImageFormat.PRIVATE -> "PRIVATE"
        ImageFormat.DEPTH16 -> "DEPTH16"
        ImageFormat.Y8 -> "Y8"
        ImageFormat.NV21 -> "NV21"
        else -> "0x%x".format(f)
    }
}
