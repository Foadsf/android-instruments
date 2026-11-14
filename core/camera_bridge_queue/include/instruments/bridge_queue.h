/*
 * Request queue for the HAL1-to-HAL3 camera bridge. The framework pushes capture requests (one
 * output buffer each); the HAL1 preview window dequeues buffers on its own schedule and enqueues
 * them filled. Results must reach the framework in frame order, so completed entries are popped
 * only from the head. Pure C, no Android, not thread-safe (the caller holds a mutex).
 */
#ifndef INSTRUMENTS_BRIDGE_QUEUE_H
#define INSTRUMENTS_BRIDGE_QUEUE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BQ_CAPACITY 32

typedef enum { BQ_FREE = 0, BQ_PENDING, BQ_DEQUEUED, BQ_DONE, BQ_ERROR } bq_state_t;

typedef struct {
    uint32_t frame;
    void *buffer; /* the framework's buffer_handle_t*; matched by identity */
    int fence;    /* acquire fence, -1 if none */
    int64_t timestamp;
    bq_state_t state;
} bq_slot_t;

typedef struct {
    bq_slot_t slot[BQ_CAPACITY];
    int head;
    int count;
} bridge_queue_t;

void bq_init(bridge_queue_t *q);
/* Appends a request; returns 0, or -1 when full. */
int bq_push(bridge_queue_t *q, uint32_t frame, void *buffer, int fence);
/* Oldest PENDING entry becomes DEQUEUED and is returned; NULL when none is pending. */
bq_slot_t *bq_dequeue(bridge_queue_t *q);
/* The DEQUEUED entry holding buffer becomes DONE with timestamp; returns 0, or -1 if unknown. */
int bq_enqueue(bridge_queue_t *q, const void *buffer, int64_t timestamp);
/* The DEQUEUED entry holding buffer goes back to PENDING (the HAL returned it unused). */
int bq_cancel(bridge_queue_t *q, const void *buffer);
/* If the head entry is DONE or ERROR, copies it to *out, frees it and returns 1; else 0. */
int bq_pop(bridge_queue_t *q, bq_slot_t *out);
/* Every PENDING or DEQUEUED entry becomes ERROR (flush, stop). */
void bq_fail_all(bridge_queue_t *q);
int bq_count_state(const bridge_queue_t *q, bq_state_t s);

#ifdef __cplusplus
}
#endif

#endif
