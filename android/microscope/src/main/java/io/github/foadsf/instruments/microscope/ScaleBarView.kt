package io.github.foadsf.instruments.microscope

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View
import io.github.foadsf.instruments.microscope.core.Optics
import kotlin.math.min

/**
 * The scale bar over the live image (microscope-scale.md): a round length (0.5, 1, 2 or 5 mm) at
 * most a third of the visible width, drawn in screen pixels from µm per stream pixel. The image is
 * shown FIT_CENTER in a view of the same size, so the shown width follows from the aspect ratio.
 */
class ScaleBarView(context: Context) : View(context) {
    private var umPerPx: Double? = null
    private var visibleW = 0
    private var aspect = 4.0 / 3.0
    private val bar = Paint().apply { color = Color.WHITE; strokeWidth = 8f; setShadowLayer(3f, 0f, 0f, Color.BLACK) }
    private val text = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE; textSize = 40f; setShadowLayer(3f, 0f, 0f, Color.BLACK)
    }

    /** [umPerStreamPx]: null hides the bar; [streamW] / [zoom]: stream pixels across the visible image. */
    fun set(umPerStreamPx: Double?, streamW: Int, streamH: Int, zoom: Int) {
        umPerPx = umPerStreamPx
        visibleW = streamW / zoom.coerceAtLeast(1)
        if (streamH > 0) aspect = streamW.toDouble() / streamH
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        val um = umPerPx ?: return
        if (visibleW <= 0) return
        val (lengthUm, lengthPx) = Optics.barUm(um, visibleW / 3) ?: return
        val shownW = min(width.toDouble(), height * aspect)
        val screenPx = (lengthPx * shownW / visibleW).toFloat()
        val left = ((width - shownW) / 2 + MARGIN).toFloat()
        val y = ((height + shownW / aspect) / 2 - BOTTOM).toFloat()
        canvas.drawLine(left, y, left + screenPx, y, bar)
        val label = if (lengthUm >= 1000) "${(lengthUm / 1000).let { if (it % 1.0 == 0.0) it.toInt() else it }} mm" else "${lengthUm.toInt()} µm"
        canvas.drawText(label, left, y - 16f, text)
    }

    private companion object {
        const val MARGIN = 32.0
        const val BOTTOM = 200.0
    }
}
