#include "bridge_pool.h"

#include <android/hardware_buffer.h>
#include <android/log.h>
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/system_properties.h>
#include <string.h>
#include <time.h>

#include "bridge_gralloc1.h"
#include "instruments/yuv_copy.h"

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "InstrumentsCameraBridge", __VA_ARGS__)
#define MAX_POOL 16
#define DUMP_PROP "persist.instruments.camera.bridge_dump"
#define DUMP_AT_PROP "persist.instruments.camera.bridge_dump_at"
#define USAGE_CAMERA_WRITE 0x20000ULL /* GRALLOC_USAGE_HW_CAMERA_WRITE; not in the NDK header */

/* Exported by libnativewindow, declared only in the VNDK headers. */
typedef const void *(*get_handle_fn)(const AHardwareBuffer *);

struct bridge_pool {
    pthread_mutex_t lock;
    pthread_cond_t freed;
    int w, h, count, usage, allocated, alloc_w, alloc_h, stride, described;
    AHardwareBuffer *ahb[MAX_POOL];
    buffer_handle_t handle[MAX_POOL];
    int busy[MAX_POOL];
    get_handle_fn get_handle;
};

bridge_pool_t *pool_create(void) {
    bridge_pool_t *p = calloc(1, sizeof *p);
    if (!p) return NULL;
    pthread_mutex_init(&p->lock, NULL);
    pthread_cond_init(&p->freed, NULL);
    void *lib = dlopen("libnativewindow.so", RTLD_NOW);
    p->get_handle = lib ? (get_handle_fn)dlsym(lib, "AHardwareBuffer_getNativeHandle") : NULL;
    p->count = 9;
    gr1_init();
    return p;
}

static void free_buffers_locked(bridge_pool_t *p) {
    for (int i = 0; i < p->allocated; ++i) AHardwareBuffer_release(p->ahb[i]);
    p->allocated = 0;
}

void pool_destroy(bridge_pool_t *p) {
    if (!p) return;
    free_buffers_locked(p);
    pthread_mutex_destroy(&p->lock);
    pthread_cond_destroy(&p->freed);
    free(p);
}

void pool_set_geometry(bridge_pool_t *p, int w, int h) {
    pthread_mutex_lock(&p->lock);
    p->w = w;
    p->h = h;
    pthread_mutex_unlock(&p->lock);
}

void pool_set_count(bridge_pool_t *p, int count) {
    pthread_mutex_lock(&p->lock);
    if (count > 0 && count <= MAX_POOL) p->count = count;
    pthread_mutex_unlock(&p->lock);
}

void pool_set_usage(bridge_pool_t *p, int usage) {
    pthread_mutex_lock(&p->lock);
    p->usage = usage;
    pthread_mutex_unlock(&p->lock);
}

static int alloc_one(bridge_pool_t *p, int i, uint64_t usage) {
    AHardwareBuffer_Desc d = {.width = (uint32_t)p->w, .height = (uint32_t)p->h, .layers = 1,
                              .format = AHARDWAREBUFFER_FORMAT_Y8Cb8Cr8_420, .usage = usage};
    return AHardwareBuffer_allocate(&d, &p->ahb[i]);
}

/* (Re)allocates when the geometry or count changed and no buffer is out; 0 or negative. */
static int ensure_allocated_locked(bridge_pool_t *p) {
    if (p->allocated == p->count && p->alloc_w == p->w && p->alloc_h == p->h) return 0;
    for (int i = 0; i < p->allocated; ++i)
        if (p->busy[i]) return 0; /* keep the current set until HAL1 gives every buffer back */
    free_buffers_locked(p);
    if (p->w <= 0 || p->h <= 0 || !p->get_handle) return -EINVAL;
    uint64_t base = AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN | USAGE_CAMERA_WRITE;
    for (int i = 0; i < p->count; ++i) {
        if (alloc_one(p, i, base | (uint32_t)p->usage) != 0 && alloc_one(p, i, base) != 0) {
            for (int j = 0; j < i; ++j) AHardwareBuffer_release(p->ahb[j]);
            return -ENOMEM;
        }
        p->handle[i] = p->get_handle(p->ahb[i]);
        p->busy[i] = 0;
    }
    p->allocated = p->count;
    p->alloc_w = p->w;
    p->alloc_h = p->h;
    AHardwareBuffer_Planes pl;
    p->stride = p->w;
    if (AHardwareBuffer_lockPlanes(p->ahb[0], AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN, -1, NULL, &pl) == 0) {
        p->stride = (int)pl.planes[0].rowStride;
        AHardwareBuffer_unlock(p->ahb[0], NULL);
    }
    LOGI("pool: %d buffers %dx%d stride %d usage 0x%x", p->allocated, p->w, p->h, p->stride, p->usage);
    return 0;
}

int pool_dequeue(bridge_pool_t *p, buffer_handle_t **buffer, int *stride) {
    struct timespec until;
    clock_gettime(CLOCK_REALTIME, &until);
    until.tv_sec += 1;
    pthread_mutex_lock(&p->lock);
    int rc = ensure_allocated_locked(p);
    while (rc == 0) {
        for (int i = 0; i < p->allocated; ++i) {
            if (!p->busy[i]) {
                p->busy[i] = 1;
                *buffer = &p->handle[i];
                *stride = p->stride;
                pthread_mutex_unlock(&p->lock);
                return 0;
            }
        }
        if (pthread_cond_timedwait(&p->freed, &p->lock, &until) == ETIMEDOUT) rc = -EBUSY;
    }
    if (rc != 0) LOGI("pool dequeue failed: %d", rc);
    pthread_mutex_unlock(&p->lock);
    return rc;
}

int pool_index(bridge_pool_t *p, buffer_handle_t *buffer) {
    long i = buffer - p->handle;
    return i >= 0 && i < p->allocated ? (int)i : -1;
}

void pool_release(bridge_pool_t *p, int index) {
    pthread_mutex_lock(&p->lock);
    if (index >= 0 && index < p->allocated) p->busy[index] = 0;
    pthread_cond_broadcast(&p->freed);
    pthread_mutex_unlock(&p->lock);
}

/* Copied frame to dump: persist.instruments.camera.bridge_dump_at, default 30 (0-based). */
static int dump_at(void) {
    char v[PROP_VALUE_MAX] = {0};
    return __system_property_get(DUMP_AT_PROP, v) > 0 && atoi(v) >= 0 ? atoi(v) : 30;
}

/* Debug evidence: with persist.instruments.camera.bridge_dump set to a path, copied frame
 * dump_at() is written there as NV21 (read back from the destination, after the copy). */
static void dump_nv21(const yuv_image_t *im, uint32_t w, uint32_t h) {
    char path[PROP_VALUE_MAX] = {0};
    if (__system_property_get(DUMP_PROP, path) <= 0) return;
    FILE *f = fopen(path, "wb");
    if (!f) return;
    for (uint32_t y = 0; y < h; ++y) fwrite(im->plane[0].data + (size_t)y * im->plane[0].row_stride, 1, w, f);
    for (uint32_t y = 0; y < h / 2; ++y)
        for (uint32_t x = 0; x < w / 2; ++x) {
            fputc(im->plane[2].data[(size_t)y * im->plane[2].row_stride + (size_t)x * im->plane[2].pixel_stride], f);
            fputc(im->plane[1].data[(size_t)y * im->plane[1].row_stride + (size_t)x * im->plane[1].pixel_stride], f);
        }
    fclose(f);
    LOGI("dumped %ux%u NV21 to %s", w, h, path);
}

int pool_copy_to(bridge_pool_t *p, int index, buffer_handle_t *fw, const camera3_stream_t *s) {
    pthread_mutex_lock(&p->lock);
    AHardwareBuffer *src = index >= 0 && index < p->allocated ? p->ahb[index] : NULL;
    uint32_t w = (uint32_t)p->alloc_w < s->width ? (uint32_t)p->alloc_w : s->width;
    uint32_t h = (uint32_t)p->alloc_h < s->height ? (uint32_t)p->alloc_h : s->height;
    int frame = p->described++, describe = frame == 0;
    pthread_mutex_unlock(&p->lock);
    if (!src || !fw) return -EINVAL;
    if (describe) gr1_describe(*fw);
    AHardwareBuffer_Planes sp;
    yuv_image_t si, di;
    if (AHardwareBuffer_lockPlanes(src, AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN, -1, NULL, &sp) != 0) return -EIO;
    int rc = sp.planeCount == 3 ? gr1_lock_ycbcr(*fw, s->width, s->height, &di) : -EINVAL;
    if (rc == 0) {
        for (int i = 0; i < 3; ++i)
            si.plane[i] = (yuv_plane_t){sp.planes[i].data, sp.planes[i].rowStride, sp.planes[i].pixelStride};
        rc = yuv420_copy(&si, &di, w & ~1u, h & ~1u) == 0 ? 0 : -EINVAL;
        if (rc == 0 && frame == dump_at()) dump_nv21(&di, w, h);
        gr1_unlock(*fw);
    }
    AHardwareBuffer_unlock(src, NULL);
    return rc;
}
