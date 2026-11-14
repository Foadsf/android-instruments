/*
 * HAL3 camera device backed by the vendor's HAL1 dual mode (open_legacy("20"), wide + tele with
 * Samsung's fusion plugins). The framework's output buffers become the HAL1 preview window, so
 * frames are written straight into them. See docs/units/camera-bridge.md.
 */
#ifndef INSTRUMENTS_CAMSHIM_BRIDGE_H
#define INSTRUMENTS_CAMSHIM_BRIDGE_H

#include "legacy_camera3.h"

/* Opens the bridge for framework camera module, using the vendor module's open_legacy.
 * static_info is the vendor's static metadata for the camera being bridged (partial-result count). */
/* Loads Samsung's fusion plugins from persist.instruments.camera.plugin_dir. Call before the vendor
 * module loads: its plugin thread looks for them at start-up. */
void bridge_preload_plugins(void);

int bridge_open(camera_module_t *vendor, const hw_module_t *module, const camera_metadata_t *static_info,
                hw_device_t **device);

#endif
