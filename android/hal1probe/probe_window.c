#include "probe_window.h"

#include "legacy_gralloc.h"

#include <android/hardware_buffer.h>
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_BUFS 16
#define DEFAULT_COUNT 6
#define FALLBACK_FORMAT AHARDWAREBUFFER_FORMAT_Y8Cb8Cr8_420
/* GRALLOC_USAGE_HW_CAMERA_WRITE; the NDK header omits the AHardwareBuffer name (VNDK only). */
#define USAGE_CAMERA_WRITE 0x20000ULL

/* AHardwareBuffer_getNativeHandle is exported by libnativewindow but declared only in the VNDK
 * header, so it is looked up at run time. The native handle is the HAL's buffer_handle_t. */
typedef const void *(*get_native_handle_fn)(const AHardwareBuffer *);

struct probe_window {
    preview_stream_ops_t ops; /* first: the HAL's window pointer is cast back to this struct */
    pthread_mutex_t lock;
    pthread_cond_t freed;
    int count, w, h, hal_format, alloc_format, hal_usage, stride, allocated, alloc_error;
    AHardwareBuffer *ahb[MAX_BUFS];
    buffer_handle_t handle[MAX_BUFS];
    int dequeued[MAX_BUFS];
    int enqueues, dequeues, cancels, timestamps, saved;
    int64_t first_ns, last_ns;
    char save_path[160];
    const gralloc_module_t *gr; /* legacy gralloc, when it loads: buffers in the HAL's own format */
    alloc_device_t *gr_alloc;
    const char *backend;
};

#ifdef __LP64__
static const char *const GRALLOC_PATHS[] = {"/system/lib64/hw/gralloc.exynos5.so", "/vendor/lib64/hw/gralloc.exynos5.so"};
#else
static const char *const GRALLOC_PATHS[] = {"/system/lib/hw/gralloc.exynos5.so", "/vendor/lib/hw/gralloc.exynos5.so"};
#endif

/* Allocates every buffer through gralloc0 in exactly the HAL's format and usage. */
static int gralloc_allocate(probe_window_t *w, int n) {
    if (!w->gr) {
        void *lib = NULL;
        for (size_t k = 0; !lib && k < sizeof GRALLOC_PATHS / sizeof GRALLOC_PATHS[0]; ++k) lib = dlopen(GRALLOC_PATHS[k], RTLD_NOW);
        w->gr = lib ? (const gralloc_module_t *)dlsym(lib, "HMI") : NULL;
        hw_device_t *dev = NULL;
        int rc = w->gr ? w->gr->common.methods->open(&w->gr->common, "gpu0", &dev) : -1;
        printf("{\"event\":\"gralloc0\",\"loaded\":%d,\"open_gpu0\":%d,\"error\":\"%s\"}\n", w->gr != NULL, rc,
               lib ? "" : dlerror());
        if (rc != 0) return -ENODEV;
        w->gr_alloc = (alloc_device_t *)dev;
    }
    int usage = w->hal_usage | GRALLOC_USAGE_SW_READ_OFTEN;
    for (int i = 0; i < n; ++i) {
        int stride = 0;
        if (w->gr_alloc->alloc(w->gr_alloc, w->w, w->h, w->hal_format, usage, &w->handle[i], &stride) != 0) {
            for (int j = 0; j < i; ++j) w->gr_alloc->free(w->gr_alloc, w->handle[j]);
            return -ENOMEM;
        }
        w->stride = stride;
    }
    w->allocated = n;
    w->alloc_format = w->hal_format;
    w->backend = "gralloc0";
    return 0;
}

/* Saves buffer i as NV21 through gralloc0 lock_ycbcr. */
static void gralloc_save(probe_window_t *w, int i) {
    struct android_ycbcr y;
    memset(&y, 0, sizeof y);
    if (!w->gr->lock_ycbcr ||
        w->gr->lock_ycbcr(w->gr, w->handle[i], GRALLOC_USAGE_SW_READ_OFTEN, 0, 0, w->w, w->h, &y) != 0) {
        printf("{\"event\":\"window_save_failed\",\"backend\":\"gralloc0\"}\n");
        return;
    }
    FILE *f = fopen(w->save_path, "wb");
    if (f) {
        for (int r = 0; r < w->h; ++r) fwrite((uint8_t *)y.y + r * y.ystride, 1, (size_t)w->w, f);
        for (int r = 0; r < w->h / 2; ++r) {
            const uint8_t *cb = (uint8_t *)y.cb + r * y.cstride, *cr = (uint8_t *)y.cr + r * y.cstride;
            for (int x = 0; x < w->w / 2; ++x) {
                fputc(cr[x * y.chroma_step], f);
                fputc(cb[x * y.chroma_step], f);
            }
        }
        fclose(f);
        printf("{\"event\":\"window_saved\",\"backend\":\"gralloc0\",\"path\":\"%s\",\"ystride\":%zu,\"cstride\":%zu,"
               "\"chroma_step\":%zu,\"cr_minus_cb\":%ld}\n", w->save_path, y.ystride, y.cstride, y.chroma_step,
               (long)((uint8_t *)y.cr - (uint8_t *)y.cb));
    }
    w->gr->unlock(w->gr, w->handle[i]);
}

static probe_window_t *self(const preview_stream_ops_t *o) { return (probe_window_t *)o; }

static int alloc_one(probe_window_t *w, int i, int format, uint64_t usage) {
    AHardwareBuffer_Desc d = {.width = (uint32_t)w->w, .height = (uint32_t)w->h, .layers = 1,
                              .format = (uint32_t)format, .usage = usage};
    return AHardwareBuffer_allocate(&d, &w->ahb[i]);
}

/* Allocates count buffers in the HAL's format, else in the fallback YUV format. */
static int ensure_allocated(probe_window_t *w) {
    if (w->allocated) return 0;
    static get_native_handle_fn get_handle;
    if (!get_handle) get_handle = (get_native_handle_fn)dlsym(dlopen("libnativewindow.so", RTLD_NOW),
                                                               "AHardwareBuffer_getNativeHandle");
    if (w->w <= 0 || w->h <= 0) return w->alloc_error = -EINVAL;
    int n = w->count > 0 && w->count <= MAX_BUFS ? w->count : DEFAULT_COUNT;
    if (gralloc_allocate(w, n) == 0) return 0;
    if (!get_handle) return w->alloc_error = -ENOSYS;
    w->backend = "ahardwarebuffer";
    uint64_t base = AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN | USAGE_CAMERA_WRITE;
    int formats[2] = {w->hal_format, FALLBACK_FORMAT};
    for (int f = 0; f < 2 && !w->allocated; ++f) {
        int i = 0;
        for (; i < n; ++i) {
            if (alloc_one(w, i, formats[f], base | (uint32_t)w->hal_usage) != 0 && alloc_one(w, i, formats[f], base) != 0)
                break;
        }
        if (i == n) {
            w->allocated = n;
            w->alloc_format = formats[f];
        } else {
            for (int j = 0; j < i; ++j) AHardwareBuffer_release(w->ahb[j]);
        }
    }
    if (!w->allocated) return w->alloc_error = -ENOMEM;
    AHardwareBuffer_Desc d;
    AHardwareBuffer_describe(w->ahb[0], &d);
    w->stride = (int)d.stride;
    if (w->stride == 0) { /* describe() reports 0 for YUV; take the Y row stride from a CPU lock */
        AHardwareBuffer_Planes p;
        if (AHardwareBuffer_lockPlanes(w->ahb[0], AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN, -1, NULL, &p) == 0) {
            w->stride = (int)p.planes[0].rowStride;
            AHardwareBuffer_unlock(w->ahb[0], NULL);
        }
        if (w->stride == 0) w->stride = w->w;
    }
    for (int i = 0; i < w->allocated; ++i) w->handle[i] = get_handle(w->ahb[i]);
    return 0;
}

static int dequeue(preview_stream_ops_t *o, buffer_handle_t **buffer, int *stride) {
    probe_window_t *w = self(o);
    pthread_mutex_lock(&w->lock);
    int rc = ensure_allocated(w);
    struct timespec until;
    clock_gettime(CLOCK_REALTIME, &until);
    until.tv_sec += 1;
    while (rc == 0) {
        for (int i = 0; i < w->allocated; ++i) {
            if (!w->dequeued[i]) {
                w->dequeued[i] = 1;
                *buffer = &w->handle[i];
                *stride = w->stride;
                w->dequeues++;
                pthread_mutex_unlock(&w->lock);
                return 0;
            }
        }
        if (pthread_cond_timedwait(&w->freed, &w->lock, &until) == ETIMEDOUT) rc = -EBUSY;
    }
    pthread_mutex_unlock(&w->lock);
    return rc;
}

static int index_of(probe_window_t *w, buffer_handle_t *b) {
    long i = b - w->handle;
    return i >= 0 && i < w->allocated ? (int)i : -1;
}

/* Writes the buffer as NV21 (Y plane, then interleaved V,U) using its real plane layout. */
static void save_nv21(probe_window_t *w, int i) {
    AHardwareBuffer_Planes p;
    if (AHardwareBuffer_lockPlanes(w->ahb[i], AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN, -1, NULL, &p) != 0) return;
    FILE *f = fopen(w->save_path, "wb");
    if (f && p.planeCount == 3) {
        for (int y = 0; y < w->h; ++y) fwrite((uint8_t *)p.planes[0].data + y * p.planes[0].rowStride, 1, (size_t)w->w, f);
        for (int y = 0; y < w->h / 2; ++y) {
            const uint8_t *u = (uint8_t *)p.planes[1].data + y * p.planes[1].rowStride;
            const uint8_t *v = (uint8_t *)p.planes[2].data + y * p.planes[2].rowStride;
            for (int x = 0; x < w->w / 2; ++x) {
                fputc(v[x * p.planes[2].pixelStride], f);
                fputc(u[x * p.planes[1].pixelStride], f);
            }
        }
        printf("{\"event\":\"window_saved\",\"path\":\"%s\",\"planes\":%u,\"y_row_stride\":%u,\"uv_pixel_stride\":%u,"
               "\"v_minus_u\":%ld}\n", w->save_path, p.planeCount, p.planes[0].rowStride, p.planes[1].pixelStride,
               (long)((uint8_t *)p.planes[2].data - (uint8_t *)p.planes[1].data));
    }
    if (f) fclose(f);
    AHardwareBuffer_unlock(w->ahb[i], NULL);
}

static int enqueue(preview_stream_ops_t *o, buffer_handle_t *b) {
    probe_window_t *w = self(o);
    pthread_mutex_lock(&w->lock);
    int i = index_of(w, b);
    if (i >= 0) {
        w->enqueues++;
        /* Save frame 30, not the first: start-up frames can be blank, which would hide whether
         * the CPU can read what the camera wrote. */
        if (!w->saved && w->enqueues == 30) {
            w->saved = 1;
            if (w->gr_alloc && w->allocated && w->backend[0] == 'g') gralloc_save(w, i);
            else save_nv21(w, i);
        }
        w->dequeued[i] = 0;
        pthread_cond_signal(&w->freed);
    }
    pthread_mutex_unlock(&w->lock);
    return i >= 0 ? 0 : -EINVAL;
}

static int cancel(preview_stream_ops_t *o, buffer_handle_t *b) {
    probe_window_t *w = self(o);
    pthread_mutex_lock(&w->lock);
    int i = index_of(w, b);
    if (i >= 0) {
        w->dequeued[i] = 0;
        w->cancels++;
        pthread_cond_signal(&w->freed);
    }
    pthread_mutex_unlock(&w->lock);
    return i >= 0 ? 0 : -EINVAL;
}

static int set_count(preview_stream_ops_t *o, int count) { self(o)->count = count; return 0; }

static int set_geometry(preview_stream_ops_t *o, int width, int height, int format) {
    probe_window_t *w = self(o);
    w->w = width;
    w->h = height;
    w->hal_format = format;
    return 0;
}

static int set_crop(preview_stream_ops_t *o, int l, int t, int r, int b) { (void)o; (void)l; (void)t; (void)r; (void)b; return 0; }
static int set_usage(preview_stream_ops_t *o, int usage) { self(o)->hal_usage = usage; return 0; }
static int set_swap(preview_stream_ops_t *o, int interval) { (void)o; (void)interval; return 0; }
static int min_undequeued(const preview_stream_ops_t *o, int *count) { (void)o; *count = 2; return 0; }
static int lock_buffer(preview_stream_ops_t *o, buffer_handle_t *b) { (void)o; (void)b; return 0; }

static int set_timestamp(preview_stream_ops_t *o, int64_t ns) {
    probe_window_t *w = self(o);
    if (!w->timestamps++) w->first_ns = ns;
    w->last_ns = ns;
    return 0;
}

probe_window_t *probe_window_create(const char *save_path) {
    probe_window_t *w = calloc(1, sizeof *w);
    if (!w) return NULL;
    w->ops = (preview_stream_ops_t){dequeue, enqueue, cancel, set_count, set_geometry, set_crop,
                                    set_usage, set_swap, min_undequeued, lock_buffer, set_timestamp};
    pthread_mutex_init(&w->lock, NULL);
    pthread_cond_init(&w->freed, NULL);
    snprintf(w->save_path, sizeof w->save_path, "%s", save_path);
    return w;
}

preview_stream_ops_t *probe_window_ops(probe_window_t *w) { return &w->ops; }

int probe_window_frames(probe_window_t *w) {
    pthread_mutex_lock(&w->lock);
    int n = w->enqueues;
    pthread_mutex_unlock(&w->lock);
    return n;
}

void probe_window_report(probe_window_t *w) {
    pthread_mutex_lock(&w->lock);
    double secs = w->timestamps > 1 ? (double)(w->last_ns - w->first_ns) / 1e9 : 0.0;
    printf("{\"event\":\"window\",\"backend\":\"%s\",\"size\":[%d,%d],\"hal_format\":\"0x%x\",\"alloc_format\":\"0x%x\",\"hal_usage\":\"0x%x\","
           "\"buffers\":%d,\"stride\":%d,\"alloc_error\":%d,\"dequeues\":%d,\"enqueues\":%d,\"cancels\":%d,"
           "\"timestamps\":%d,\"fps_by_timestamp\":%.1f}\n",
           w->backend ? w->backend : "none", w->w, w->h, w->hal_format, w->alloc_format, w->hal_usage, w->allocated, w->stride, w->alloc_error,
           w->dequeues, w->enqueues, w->cancels, w->timestamps, secs > 0 ? (w->timestamps - 1) / secs : 0.0);
    pthread_mutex_unlock(&w->lock);
}
