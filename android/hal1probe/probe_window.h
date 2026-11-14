/*
 * A HAL1 preview window (preview_stream_ops) backed by AHardwareBuffers, standing in for the
 * consumer the camera bridge will provide. Enqueued buffers are returned to the free list at
 * once; the first one is saved as NV21 for inspection.
 */
#ifndef INSTRUMENTS_PROBE_WINDOW_H
#define INSTRUMENTS_PROBE_WINDOW_H

#include "legacy_camera_hal1.h"

typedef struct probe_window probe_window_t;

probe_window_t *probe_window_create(const char *save_path);
preview_stream_ops_t *probe_window_ops(probe_window_t *w);
int probe_window_frames(probe_window_t *w);
/* Prints one JSON line with what the HAL asked for and what happened. */
void probe_window_report(probe_window_t *w);

#endif
