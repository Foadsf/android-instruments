/*
 * The bridge's private HAL1 buffer pool. Samsung's HAL1 only fills the buffers it dequeued at
 * start_preview, so it gets a fixed set of AHardwareBuffers owned by the bridge, and each filled
 * frame is copied (core/yuv_copy) into the framework's buffer for the oldest pending request.
 * Thread-safe.
 */
#ifndef INSTRUMENTS_CAMSHIM_BRIDGE_POOL_H
#define INSTRUMENTS_CAMSHIM_BRIDGE_POOL_H

#include "legacy_camera3.h"

typedef struct bridge_pool bridge_pool_t;

bridge_pool_t *pool_create(void);
void pool_destroy(bridge_pool_t *p);
/* Window settings from HAL1; buffers are (re)allocated on the next dequeue when they change. */
void pool_set_geometry(bridge_pool_t *p, int w, int h);
void pool_set_count(bridge_pool_t *p, int count);
void pool_set_usage(bridge_pool_t *p, int usage);
/* A free pool buffer, waiting up to 1 s; 0 or a negative errno. */
int pool_dequeue(bridge_pool_t *p, buffer_handle_t **buffer, int *stride);
/* Index of a pool buffer, -1 if the pointer is not one of ours. */
int pool_index(bridge_pool_t *p, buffer_handle_t *buffer);
void pool_release(bridge_pool_t *p, int index);
/* Copies pool buffer index into the framework buffer (locked through gralloc1); 0 or negative. */
int pool_copy_to(bridge_pool_t *p, int index, buffer_handle_t *framework, const camera3_stream_t *stream);

#endif
