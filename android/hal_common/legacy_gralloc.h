/*
 * Minimal copy of the legacy gralloc (gralloc0) interface, hardware/libhardware/include/hardware/
 * gralloc.h and system/core/include/system/graphics.h (android_ycbcr), field for field. The
 * Note8's LineageOS 20 ROM still ships gralloc.exynos5.so behind the passthrough allocator.
 */
#ifndef INSTRUMENTS_LEGACY_GRALLOC_H
#define INSTRUMENTS_LEGACY_GRALLOC_H

#include <stddef.h>
#include <stdint.h>

#include "legacy_camera_hal1.h"

#define GRALLOC_USAGE_SW_READ_OFTEN 0x00000003

struct android_ycbcr {
    void *y;
    void *cb;
    void *cr;
    size_t ystride;
    size_t cstride;
    size_t chroma_step;
    uint32_t reserved[8];
};

typedef struct gralloc_module {
    struct hw_module_t common;
    int (*registerBuffer)(const struct gralloc_module *m, buffer_handle_t h);
    int (*unregisterBuffer)(const struct gralloc_module *m, buffer_handle_t h);
    int (*lock)(const struct gralloc_module *m, buffer_handle_t h, int usage, int l, int t, int w, int hgt, void **vaddr);
    int (*unlock)(const struct gralloc_module *m, buffer_handle_t h);
    int (*perform)(const struct gralloc_module *m, int operation, ...);
    int (*lock_ycbcr)(const struct gralloc_module *m, buffer_handle_t h, int usage, int l, int t, int w, int hgt,
                      struct android_ycbcr *ycbcr);
    void *lockAsync, *unlockAsync, *lockAsync_ycbcr, *getTransportSize, *validateBufferSize;
    void *reserved_proc[1];
} gralloc_module_t;

typedef struct alloc_device {
    struct hw_device_t common;
    int (*alloc)(struct alloc_device *dev, int w, int h, int format, int usage, buffer_handle_t *handle, int *stride);
    int (*free)(struct alloc_device *dev, buffer_handle_t handle);
    void (*dump)(struct alloc_device *dev, char *buff, int buff_len);
    void *reserved_proc[7];
} alloc_device_t;

#endif
