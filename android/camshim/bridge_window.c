/*
 * The HAL1 preview window of the bridge. HAL1 fills the bridge's own pool (it only fills buffers it
 * registered at start_preview); enqueue only queues the filled buffer, and a copier thread copies
 * it into the framework buffer of the oldest pending request and delivers the result. Copying or
 * calling the framework on HAL1's enqueue thread stalled Samsung's dual pipeline after ~50 frames.
 */
#include <android/log.h>
#include <errno.h>
#include <poll.h>
#include <unistd.h>

#include "bridge_internal.h"

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "InstrumentsCameraBridge", __VA_ARGS__)

static bridge_t *of_window(const preview_stream_ops_t *w) { return ((const bridge_window_t *)w)->b; }

static void wait_fence(int fence) {
    if (fence < 0) return;
    struct pollfd p = {fence, POLLIN, 0};
    poll(&p, 1, 1000);
    close(fence);
}

static void count_frame(bridge_t *b, int outcome) {
    pthread_mutex_lock(&b->lock);
    b->stats[outcome]++;
    int total = b->stats[0] + b->stats[1] + b->stats[2];
    if (total % 100 == 1)
        LOGI("frames: copied %d, dropped (no request) %d, copy failed %d", b->stats[0], b->stats[1], b->stats[2]);
    pthread_mutex_unlock(&b->lock);
}

/* Copies one filled pool buffer into the oldest pending request's buffer, or drops it. */
static void copy_one(bridge_t *b, filled_t f) {
    pthread_mutex_lock(&b->lock);
    bq_slot_t *s = bq_dequeue(&b->q);
    void *target = s ? s->buffer : NULL;
    int fence = s ? s->fence : -1;
    if (s) s->fence = -1;
    camera3_stream_t *stream = b->stream;
    pthread_mutex_unlock(&b->lock);
    if (!target) {
        pool_release(b->pool, f.index);
        count_frame(b, 1);
        return;
    }
    wait_fence(fence);
    int rc = pool_copy_to(b->pool, f.index, (buffer_handle_t *)target, stream);
    pool_release(b->pool, f.index);
    pthread_mutex_lock(&b->lock);
    if (rc == 0) bq_enqueue(&b->q, target, f.ts);
    else bq_fail(&b->q, target);
    pthread_mutex_unlock(&b->lock);
    count_frame(b, rc == 0 ? 0 : 2);
    bridge_deliver_ready(b);
}

static void *copier_main(void *arg) {
    bridge_t *b = arg;
    pthread_mutex_lock(&b->lock);
    for (;;) {
        while (!b->filled_count && !b->copier_stop) pthread_cond_wait(&b->filled_cv, &b->lock);
        if (!b->filled_count) break; /* stop requested and nothing left */
        filled_t f = b->filled[b->filled_head];
        b->filled_head = (b->filled_head + 1) % FILLED_CAP;
        b->filled_count--;
        pthread_mutex_unlock(&b->lock);
        copy_one(b, f);
        pthread_mutex_lock(&b->lock);
    }
    pthread_mutex_unlock(&b->lock);
    return NULL;
}

static int win_dequeue(preview_stream_ops_t *w, buffer_handle_t **buffer, int *stride) {
    return pool_dequeue(of_window(w)->pool, buffer, stride);
}

static int win_enqueue(preview_stream_ops_t *w, buffer_handle_t *buffer) {
    bridge_t *b = of_window(w);
    int index = pool_index(b->pool, buffer);
    if (index < 0) return -EINVAL;
    pthread_mutex_lock(&b->lock);
    int ok = b->filled_count < FILLED_CAP;
    if (ok) {
        b->filled[(b->filled_head + b->filled_count++) % FILLED_CAP] = (filled_t){index, b->last_ts};
        pthread_cond_signal(&b->filled_cv);
    }
    pthread_mutex_unlock(&b->lock);
    if (!ok) pool_release(b->pool, index); /* cannot happen with a pool smaller than the ring */
    return 0;
}

static int win_cancel(preview_stream_ops_t *w, buffer_handle_t *buffer) {
    bridge_t *b = of_window(w);
    int index = pool_index(b->pool, buffer);
    pool_release(b->pool, index);
    return index >= 0 ? 0 : -EINVAL;
}

static int win_count(preview_stream_ops_t *w, int n) { pool_set_count(of_window(w)->pool, n); return 0; }
static int win_usage(preview_stream_ops_t *w, int u) { pool_set_usage(of_window(w)->pool, u); return 0; }

static int win_geometry(preview_stream_ops_t *w, int x, int y, int f) {
    LOGI("window geometry %dx%d format 0x%x", x, y, f);
    pool_set_geometry(of_window(w)->pool, x, y);
    return 0;
}

static int win_set_timestamp(preview_stream_ops_t *w, int64_t ts) {
    bridge_t *b = of_window(w);
    pthread_mutex_lock(&b->lock);
    b->last_ts = ts;
    pthread_mutex_unlock(&b->lock);
    return 0;
}

static int win_ok(preview_stream_ops_t *w, int v) { (void)w, (void)v; return 0; }
static int win_crop(preview_stream_ops_t *w, int l, int t, int r, int bt) { (void)w, (void)l, (void)t, (void)r, (void)bt; return 0; }
static int win_min_undequeued(const preview_stream_ops_t *w, int *count) { (void)w; *count = 2; return 0; }
static int win_lock(preview_stream_ops_t *w, buffer_handle_t *h) { (void)w, (void)h; return 0; }

void bridge_window_init(bridge_t *b) {
    static const preview_stream_ops_t win = {win_dequeue,  win_enqueue, win_cancel, win_count,
                                             win_geometry, win_crop,    win_usage,  win_ok,
                                             win_min_undequeued, win_lock, win_set_timestamp};
    b->window.ops = win;
    b->window.b = b;
    pthread_cond_init(&b->filled_cv, NULL);
    b->copier_valid = pthread_create(&b->copier, NULL, copier_main, b) == 0;
}

void bridge_window_stop(bridge_t *b) {
    pthread_mutex_lock(&b->lock);
    b->copier_stop = 1;
    pthread_cond_broadcast(&b->filled_cv);
    pthread_mutex_unlock(&b->lock);
    if (b->copier_valid) pthread_join(b->copier, NULL);
    b->copier_valid = 0;
    pthread_cond_destroy(&b->filled_cv);
}
