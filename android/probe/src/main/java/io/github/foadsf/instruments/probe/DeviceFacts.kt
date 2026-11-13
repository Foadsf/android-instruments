package io.github.foadsf.instruments.probe

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Phone identity through public APIs. Root is detected (presence of an `su` binary) and
 * reported, never used. The hardware serial is deliberately not collected: results are
 * committed to a public repository. Adapted from parallax's DeviceProbe.
 */
object DeviceFacts {
    fun collect(ctx: Context): Map<String, Any?> {
        val mem = ActivityManager.MemoryInfo().also { ctx.getSystemService(ActivityManager::class.java).getMemoryInfo(it) }
        return linkedMapOf(
            "manufacturer" to Build.MANUFACTURER,
            "model" to Build.MODEL,
            "device" to Build.DEVICE,
            "android_release" to Build.VERSION.RELEASE,
            "sdk_int" to Build.VERSION.SDK_INT,
            "security_patch" to Build.VERSION.SECURITY_PATCH,
            "build_display" to Build.DISPLAY,
            "build_type" to Build.TYPE,
            "rom" to rom(),
            "soc" to soc(),
            "board_platform" to prop("ro.board.platform"),
            "abis" to Build.SUPPORTED_ABIS.toList(),
            "cpu_cores" to Runtime.getRuntime().availableProcessors(),
            "cpu_max_khz" to cpuMaxKhz(),
            "ram_bytes" to mem.totalMem,
            "su_binary" to suPath(),
        )
    }

    fun prop(key: String): String = runCatching {
        val p = ProcessBuilder("getprop", key).redirectErrorStream(true).start()
        val out = p.inputStream.bufferedReader().readText().trim()
        p.waitFor(2, TimeUnit.SECONDS)
        out
    }.getOrDefault("")

    private fun rom(): Map<String, String> = linkedMapOf(
        "lineage" to prop("ro.lineage.version"),
        "oneui" to prop("ro.build.version.oneui"),
        "incremental" to Build.VERSION.INCREMENTAL,
    ).filterValues { it.isNotEmpty() }

    private fun soc(): String =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && Build.SOC_MODEL != Build.UNKNOWN) {
            "${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}".trim()
        } else {
            prop("ro.hardware.chipname").ifEmpty { Build.HARDWARE }
        }

    private fun cpuMaxKhz(): List<Long> = (0 until Runtime.getRuntime().availableProcessors()).map { i ->
        runCatching { File("/sys/devices/system/cpu/cpu$i/cpufreq/cpuinfo_max_freq").readText().trim().toLong() }
            .getOrDefault(-1L)
    }

    private fun suPath(): String? = listOf(
        "/system/bin/su", "/system/xbin/su", "/sbin/su", "/system_ext/bin/su", "/debug_ramdisk/su",
        "/data/adb/magisk", "/data/adb/ksu",
    ).firstOrNull { runCatching { File(it).exists() }.getOrDefault(false) }
}
