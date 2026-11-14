/*
 * Telephoto-only mode of the bridge. HAL1 camera "3" (the telephoto alone, no fusion, so no
 * fallback to a wide-camera crop) refuses standard window buffers (its ISP output node only takes
 * its private format), but without a window it delivers NV21 frames by data callback. The callback
 * memory is released when the callback returns, so each frame is copied into a CPU slot there, and
 * the copier thread copies the slot into the framework buffer (two copies of about 2.3 MB at
 * 1440x1080).
 */
#include <android/log.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "bridge_gralloc1.h"
#include "bridge_internal.h"
#include "instruments/yuv_copy.h"

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "InstrumentsCameraBridge", __VA_ARGS__)

static size_t frame_bytes(uint32_t w, uint32_t h) { return (size_t)w * h * 3 / 2; }

/* Camera 3 reports timestampSource REALTIME: shutter timestamps are CLOCK_BOOTTIME. */
static int64_t boottime_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_BOOTTIME, &t);
    return (int64_t)t.tv_sec * 1000000000LL + t.tv_nsec;
}

static int any_busy_locked(bridge_t *b) {
    for (int i = 0; i < TELE_SLOTS; ++i)
        if (b->slot_busy[i]) return 1;
    return b->filled_count > 0;
}

int tele_alloc(bridge_t *b, uint32_t w, uint32_t h) {
    size_t need = frame_bytes(w, h);
    pthread_mutex_lock(&b->lock);
    for (int tries = 0; any_busy_locked(b) && tries < 100; ++tries) { /* copier drains after stop */
        pthread_mutex_unlock(&b->lock);
        usleep(10000);
        pthread_mutex_lock(&b->lock);
    }
    int rc = any_busy_locked(b) ? -EBUSY : 0;
    if (rc == 0 && need > b->slot_cap) {
        for (int i = 0; i < TELE_SLOTS && rc == 0; ++i) {
            uint8_t *p = realloc(b->slot[i], need);
            if (p) b->slot[i] = p;
            else rc = -ENOMEM;
        }
        if (rc == 0) b->slot_cap = need;
    }
    if (rc == 0) {
        b->slot_w = w;
        b->slot_h = h;
    }
    pthread_mutex_unlock(&b->lock);
    LOGI("tele slots %ux%u: %d", w, h, rc);
    return rc;
}

void tele_free(bridge_t *b) {
    for (int i = 0; i < TELE_SLOTS; ++i) free(b->slot[i]);
    memset(b->slot, 0, sizeof b->slot);
    b->slot_cap = 0;
}

void tele_on_frame(bridge_t *b, const void *data, size_t size, unsigned int index) {
    int64_t ts = boottime_ns();
    pthread_mutex_lock(&b->lock);
    size_t one = frame_bytes(b->slot_w, b->slot_h);
    int slot = -1;
    for (int i = 0; b->previewing && one && one <= b->slot_cap && i < TELE_SLOTS && slot < 0; ++i)
        if (!b->slot_busy[i]) slot = i;
    if (slot >= 0) b->slot_busy[slot] = 1;
    else b->stats[1]++; /* no free slot (copier behind) or not running: drop */
    pthread_mutex_unlock(&b->lock);
    if (slot < 0) return;
    /* The HAL may pass its whole heap; index selects the frame when the heap holds several. */
    size_t off = size >= ((size_t)index + 1) * one ? (size_t)index * one : 0;
    if (!data || size < off + one) {
        tele_release(b, slot);
        return;
    }
    memcpy(b->slot[slot], (const uint8_t *)data + off, one);
    if (bridge_queue_filled(b, slot, ts) != 0) tele_release(b, slot);
}

int tele_copy_to(bridge_t *b, int slot, buffer_handle_t *fw, const camera3_stream_t *s) {
    pthread_mutex_lock(&b->lock);
    uint8_t *src = slot >= 0 && slot < TELE_SLOTS ? b->slot[slot] : NULL;
    uint32_t sw = b->slot_w, sh = b->slot_h;
    int frame = b->tele_frames++;
    pthread_mutex_unlock(&b->lock);
    yuv_image_t si, di;
    if (!src || !fw || yuv_describe_nv21(src, sw, sh, &si) != 0) return -EINVAL;
    if (frame == 0) gr1_describe(*fw);
    uint32_t w = sw < s->width ? sw : s->width, h = sh < s->height ? sh : s->height;
    int rc = gr1_lock_ycbcr(*fw, s->width, s->height, &di);
    if (rc != 0) return rc;
    rc = yuv420_copy(&si, &di, w & ~1u, h & ~1u) == 0 ? 0 : -EINVAL;
    if (rc == 0) bridge_dump_maybe(frame, &di, w, h);
    gr1_unlock(*fw);
    return rc;
}

void tele_release(bridge_t *b, int slot) {
    pthread_mutex_lock(&b->lock);
    if (slot >= 0 && slot < TELE_SLOTS) b->slot_busy[slot] = 0;
    pthread_mutex_unlock(&b->lock);
}
