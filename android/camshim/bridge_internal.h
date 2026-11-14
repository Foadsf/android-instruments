/* The bridge's state, shared by bridge.c (camera3 device) and bridge_window.c (HAL1 window). */
#ifndef INSTRUMENTS_CAMSHIM_BRIDGE_INTERNAL_H
#define INSTRUMENTS_CAMSHIM_BRIDGE_INTERNAL_H

#include <pthread.h>

#include "bridge_meta.h"
#include "bridge_pool.h"
#include "instruments/bridge_queue.h"
#include "legacy_camera3.h"

#define MAX_TEMPLATES 8
#define FILLED_CAP 16 /* more than the pool: every entry holds a pool buffer */

typedef struct bridge bridge_t;
typedef struct {
    preview_stream_ops_t ops; /* first: the HAL1 window pointer is cast back to this */
    bridge_t *b;
} bridge_window_t;

typedef struct {
    int index; /* pool buffer HAL1 filled */
    int64_t ts;
} filled_t;

struct bridge {
    camera3_device_t dev; /* first: the framework's device pointer is cast back to this */
    camera3_device_ops_t ops;
    bridge_window_t window;
    const camera3_callback_ops_t *cb;
    camera_device_t *hal1;
    pthread_mutex_t lock; /* queue, filled ring, stats, last_settings, last_ts */
    pthread_mutex_t ctl;  /* HAL1 preview start/stop and configuration */
    bridge_queue_t q;
    bridge_pool_t *pool;
    int stats[3]; /* frames copied, dropped for lack of a request, copy failed */
    camera3_stream_t *stream;
    camera_metadata_t *last_settings;
    camera_metadata_t *defaults[MAX_TEMPLATES];
    meta_api_t meta;
    pthread_t starter; /* runs start_preview off the request thread */
    int starter_valid, starting, previewing, partial_count;
    int64_t last_ts;
    /* Filled frames wait here for the copier thread, so HAL1's enqueue returns at once. */
    filled_t filled[FILLED_CAP];
    int filled_head, filled_count, copier_stop, copier_valid;
    pthread_cond_t filled_cv;
    pthread_t copier;
};

/* Pops every result that is ready, in frame order, and sends it to the framework. */
void bridge_deliver_ready(bridge_t *b);
/* Fills in the window ops and starts the copier thread. */
void bridge_window_init(bridge_t *b);
/* Stops and joins the copier thread (after HAL1 has stopped). */
void bridge_window_stop(bridge_t *b);

#endif
