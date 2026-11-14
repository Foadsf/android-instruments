/*
 * CPU access to framework camera buffers through the device's gralloc1 module (on the Note8 the
 * Mali gralloc.exynos5.so, module API 1.0). The camera provider has already imported those
 * buffers, so they are locked as they are; AHardwareBuffer_createFromHandle refused them (-22).
 */
#ifndef INSTRUMENTS_CAMSHIM_BRIDGE_GRALLOC1_H
#define INSTRUMENTS_CAMSHIM_BRIDGE_GRALLOC1_H

#include "instruments/yuv_copy.h"
#include "legacy_camera_hal1.h"

/* Loads the module and resolves the functions once; 0 or negative. */
int gr1_init(void);
/* Logs the buffer's width, height, format and stride as gralloc1 reports them. */
void gr1_describe(buffer_handle_t buffer);
/* Locks a YUV buffer for CPU writing and describes its planes; 0 or negative. */
int gr1_lock_ycbcr(buffer_handle_t buffer, uint32_t w, uint32_t h, yuv_image_t *out);
void gr1_unlock(buffer_handle_t buffer);

#endif
