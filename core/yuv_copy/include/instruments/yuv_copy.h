/*
 * Copies a 4:2:0 YUV image between two buffers whose plane layouts may differ (NV12, NV21, I420,
 * padded rows), described the way AHardwareBuffer_lockPlanes and android_ycbcr describe them.
 * The camera bridge copies HAL1 frames from its private pool into framework buffers with it.
 * Pure C, no Android: tested on the host.
 */
#ifndef INSTRUMENTS_YUV_COPY_H
#define INSTRUMENTS_YUV_COPY_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint8_t *data;
    uint32_t row_stride;   /* bytes between rows */
    uint32_t pixel_stride; /* bytes between samples in a row: 1 planar, 2 interleaved chroma */
} yuv_plane_t;

typedef struct {
    yuv_plane_t plane[3]; /* Y, U (Cb), V (Cr) */
} yuv_image_t;

/* Copies the w x h image (w and h even). Returns 0, or -1 if a size is odd or zero, a plane is
 * NULL, a pixel stride is 0, or a row stride is too small for its row. */
int yuv420_copy(const yuv_image_t *src, const yuv_image_t *dst, uint32_t w, uint32_t h);

#ifdef __cplusplus
}
#endif

#endif
