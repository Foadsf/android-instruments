/*
 * Merges N aligned 8-bit YUV 4:2:0 frames of a static scene into their per-pixel mean
 * (docs/units/burst-merge.md). Frames are added one at a time to a uint32 accumulator, so memory
 * does not grow with N. No spatial filtering: N identical frames give that frame back exactly.
 * Pure C, no Android: tested on the host.
 */
#ifndef INSTRUMENTS_BURST_MERGE_H
#define INSTRUMENTS_BURST_MERGE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BURST_MERGE_OK 0
#define BURST_MERGE_EINVAL (-1)   /* odd or zero size, NULL plane, short stride, size mismatch */
#define BURST_MERGE_EEMPTY (-2)   /* finish with no frame added */
#define BURST_MERGE_EFULL (-3)    /* more than BURST_MERGE_MAX_FRAMES frames */
#define BURST_MERGE_ENOMEM (-4)

/* 255 * 2^24 < 2^32: a uint32 sum of 8-bit samples cannot overflow up to this many frames. */
#define BURST_MERGE_MAX_FRAMES 16777216u

typedef struct {
    const uint8_t *plane[3]; /* Y, U, V: planar, one byte per sample */
    uint32_t stride[3];      /* bytes between rows; >= the plane's width */
    uint32_t w, h;           /* luma size; chroma planes are w/2 x h/2 */
} burst_frame_t;

typedef struct {
    uint32_t w, h, n;
    uint32_t *sum; /* w*h luma sums, then w/2*h/2 U sums, then w/2*h/2 V sums */
} burst_merge_t;

/* Allocates the accumulator for w x h frames (w, h even, nonzero). */
int burst_merge_init(burst_merge_t *m, uint32_t w, uint32_t h);

/* Adds one frame; it must have the accumulator's size. Nothing changes on error. */
int burst_merge_add(burst_merge_t *m, const burst_frame_t *f);

/* Luma mean in Q8.8: round(256 * sum / n), ties up. stride is in uint16 elements, >= w. */
int burst_merge_finish_y16(const burst_merge_t *m, uint16_t *y16, uint32_t stride);

/* Packed I420 (w*h*3/2 bytes): each sample round(sum / n), ties up. */
int burst_merge_finish_i420(const burst_merge_t *m, uint8_t *out);

void burst_merge_free(burst_merge_t *m);

/* Describes a packed I420 buffer of w x h as a frame. */
int burst_frame_from_i420(const uint8_t *buf, uint32_t w, uint32_t h, burst_frame_t *out);

#ifdef __cplusplus
}
#endif

#endif
