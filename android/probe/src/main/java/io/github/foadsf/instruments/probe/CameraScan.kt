package io.github.foadsf.instruments.probe

import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.os.Build
import io.github.foadsf.instruments.probe.core.CameraInfo
import io.github.foadsf.instruments.probe.core.EventLog

/**
 * Finds every camera ID the app can read characteristics for: the IDs the framework lists, every
 * numeric ID in [SCAN_RANGE] (vendors hide physical and auxiliary cameras from the list), and the
 * physical IDs named by any logical camera found.
 */
class CameraScan(private val manager: CameraManager, private val log: EventLog) {
    data class Entry(val id: String, val listed: Boolean, val chars: CameraCharacteristics?, val error: String?)

    fun scan(): List<Entry> {
        val listed = runCatching { manager.cameraIdList.toList() }
            .onFailure { e -> log.error("camera.list_failed") { mapOf("error" to e.toString()) } }
            .getOrDefault(emptyList())
        log.info("camera.listed") { mapOf("ids" to listed) }
        val found = linkedMapOf<String, Entry>()
        val queue = ArrayDeque(listed + SCAN_RANGE.map { it.toString() })
        while (queue.isNotEmpty()) {
            val id = queue.removeFirst()
            if (id in found) continue
            val entry = read(id, id in listed) ?: continue
            found[id] = entry
            entry.chars?.physicalCameraIds?.forEach { if (it !in found) queue.addLast(it) }
        }
        log.info("camera.scanned") { mapOf("found" to found.keys.toList(), "hidden" to (found.keys - listed.toSet()).toList()) }
        return found.values.toList()
    }

    /** null when the ID does not exist; an Entry with an error when it exists but cannot be read. */
    private fun read(id: String, listed: Boolean): Entry? = try {
        Entry(id, listed, manager.getCameraCharacteristics(id), null)
    } catch (e: IllegalArgumentException) {
        if (listed) Entry(id, true, null, e.toString()) else null
    } catch (e: Exception) {
        log.warn("camera.read_failed") { mapOf("id" to id, "error" to e.toString()) }
        Entry(id, listed, null, e.toString())
    }

    fun toJson(entries: List<Entry>): List<Map<String, Any?>> = entries.map { e ->
        linkedMapOf(
            "id" to e.id,
            "listed" to e.listed,
            "physical_ids" to e.chars?.physicalCameraIds?.toList()?.sorted(),
            "error" to e.error,
            "characteristics" to e.chars?.let(CharacteristicsDump::toMap),
        )
    }

    fun cameraInfo(entries: List<Entry>): List<CameraInfo> = entries.mapNotNull { e ->
        val c = e.chars ?: return@mapNotNull null
        val caps = c.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)?.toSet().orEmpty()
        CameraInfo(
            id = e.id,
            isLogicalMulti = CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA in caps,
            physicalIds = c.physicalCameraIds.toList().sorted(),
            yuvSizes = CharacteristicsDump.yuvSizes(c),
        )
    }

    /** Camera ID sets the framework says can stream concurrently; null below API 30 or on error. */
    fun concurrentIdSets(): List<List<String>>? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        return runCatching { manager.concurrentCameraIds.map { it.toList().sorted() } }
            .onFailure { e -> log.warn("camera.concurrent_ids_failed") { mapOf("error" to e.toString()) } }
            .getOrNull()
    }

    companion object {
        val SCAN_RANGE = 0..127
    }
}
