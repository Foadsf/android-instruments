/* HAL1 device callbacks for the bridge: errors are logged, preview data arrives through the
 * window (not the data callback), and get_memory maps the HAL's ION fds. */
#ifndef INSTRUMENTS_CAMSHIM_BRIDGE_HAL1_H
#define INSTRUMENTS_CAMSHIM_BRIDGE_HAL1_H

#include "legacy_camera_hal1.h"

void bridge_hal1_set_callbacks(camera_device_t *dev);

#endif
