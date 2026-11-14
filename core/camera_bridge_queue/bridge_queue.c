#include "instruments/bridge_queue.h"

#include <string.h>

static bq_slot_t *at(bridge_queue_t *q, int i) { return &q->slot[(q->head + i) % BQ_CAPACITY]; }

void bq_init(bridge_queue_t *q) { memset(q, 0, sizeof *q); }

int bq_push(bridge_queue_t *q, uint32_t frame, void *buffer, int fence) {
    if (q->count == BQ_CAPACITY) return -1;
    bq_slot_t *s = at(q, q->count++);
    s->frame = frame;
    s->buffer = buffer;
    s->fence = fence;
    s->timestamp = 0;
    s->state = BQ_PENDING;
    return 0;
}

bq_slot_t *bq_dequeue(bridge_queue_t *q) {
    for (int i = 0; i < q->count; ++i) {
        bq_slot_t *s = at(q, i);
        if (s->state == BQ_PENDING) {
            s->state = BQ_DEQUEUED;
            return s;
        }
    }
    return NULL;
}

static bq_slot_t *find_dequeued(bridge_queue_t *q, const void *buffer) {
    for (int i = 0; i < q->count; ++i) {
        bq_slot_t *s = at(q, i);
        if (s->state == BQ_DEQUEUED && s->buffer == buffer) return s;
    }
    return NULL;
}

int bq_enqueue(bridge_queue_t *q, const void *buffer, int64_t timestamp) {
    bq_slot_t *s = find_dequeued(q, buffer);
    if (!s) return -1;
    s->state = BQ_DONE;
    s->timestamp = timestamp;
    return 0;
}

int bq_cancel(bridge_queue_t *q, const void *buffer) {
    bq_slot_t *s = find_dequeued(q, buffer);
    if (!s) return -1;
    s->state = BQ_PENDING;
    return 0;
}

int bq_pop(bridge_queue_t *q, bq_slot_t *out) {
    if (q->count == 0) return 0;
    bq_slot_t *s = at(q, 0);
    if (s->state != BQ_DONE && s->state != BQ_ERROR) return 0;
    *out = *s;
    s->state = BQ_FREE;
    q->head = (q->head + 1) % BQ_CAPACITY;
    q->count--;
    return 1;
}

void bq_fail_all(bridge_queue_t *q) {
    for (int i = 0; i < q->count; ++i) {
        bq_slot_t *s = at(q, i);
        if (s->state == BQ_PENDING || s->state == BQ_DEQUEUED) s->state = BQ_ERROR;
    }
}

int bq_count_state(const bridge_queue_t *q, bq_state_t st) {
    int n = 0;
    for (int i = 0; i < q->count; ++i)
        if (q->slot[(q->head + i) % BQ_CAPACITY].state == st) ++n;
    return n;
}
