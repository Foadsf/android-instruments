/* HAL1 device callbacks for the bridge: errors are logged, get_memory maps the HAL's ION fds, and
 * preview data arrives through the window (dual mode) or the data callback (telephoto-only mode,
 * preview_frames set: frames go to tele_on_frame). */
#ifndef INSTRUMENTS_CAMSHIM_BRIDGE_HAL1_H
#define INSTRUMENTS_CAMSHIM_BRIDGE_HAL1_H

#include "legacy_camera_hal1.h"

struct bridge;
void bridge_hal1_set_callbacks(camera_device_t *dev, struct bridge *b, int preview_frames);

#endif
