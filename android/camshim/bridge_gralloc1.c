#include "bridge_gralloc1.h"

#include <android/log.h>
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <string.h>
#include <unistd.h>

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "InstrumentsCameraBridge", __VA_ARGS__)
#ifdef __LP64__
#define GRALLOC_PATH "/system/lib64/hw/gralloc.exynos5.so"
#else
#define GRALLOC_PATH "/system/lib/hw/gralloc.exynos5.so"
#endif

/* hardware/libhardware/include/hardware/gralloc1.h and system/graphics.h, field for field */
enum { FN_GET_DIMENSIONS = 10, FN_GET_FORMAT = 11, FN_GET_STRIDE = 13, FN_GET_NUM_FLEX_PLANES = 17,
       FN_LOCK_FLEX = 19, FN_UNLOCK = 20 };
enum { FLEX_Y = 1, FLEX_CB = 2, FLEX_CR = 4 };
#define PRODUCER_CPU_WRITE_OFTEN ((1ULL << 6) | (1ULL << 5))
#define MAX_PLANES 4

typedef struct { int32_t left, top, width, height; } gr1_rect_t;
typedef struct {
    uint8_t *top_left;
    int component;
    int32_t bits_per_component, bits_used, h_increment, v_increment, h_subsampling, v_subsampling;
} flex_plane_t;
typedef struct {
    int format;
    uint32_t num_planes;
    flex_plane_t *planes;
} flex_layout_t;

typedef struct gr1_device {
    struct hw_device_t common;
    void (*get_capabilities)(struct gr1_device *, uint32_t *, int32_t *);
    void *(*get_function)(struct gr1_device *, int32_t);
} gr1_device_t;

typedef int32_t (*dims_fn)(gr1_device_t *, buffer_handle_t, uint32_t *, uint32_t *);
typedef int32_t (*u32_fn)(gr1_device_t *, buffer_handle_t, uint32_t *);
typedef int32_t (*lock_flex_fn)(gr1_device_t *, buffer_handle_t, uint64_t, uint64_t, const gr1_rect_t *,
                                flex_layout_t *, int32_t);
typedef int32_t (*unlock_fn)(gr1_device_t *, buffer_handle_t, int32_t *);

static gr1_device_t *g_dev;
static dims_fn g_dims;
static u32_fn g_format, g_stride, g_num_planes;
static lock_flex_fn g_lock_flex;
static unlock_fn g_unlock;
static pthread_once_t g_once = PTHREAD_ONCE_INIT;

static void load(void) {
    void *lib = dlopen(GRALLOC_PATH, RTLD_NOW);
    hw_module_t *m = lib ? (hw_module_t *)dlsym(lib, "HMI") : NULL;
    hw_device_t *dev = NULL;
    int rc = m && m->module_api_version >= 0x100 ? m->methods->open(m, "gralloc", &dev) : -ENODEV;
    if (rc != 0 || !dev) {
        LOGI("gralloc1 open failed: %d", rc);
        return;
    }
    g_dev = (gr1_device_t *)dev;
    g_dims = (dims_fn)g_dev->get_function(g_dev, FN_GET_DIMENSIONS);
    g_format = (u32_fn)g_dev->get_function(g_dev, FN_GET_FORMAT);
    g_stride = (u32_fn)g_dev->get_function(g_dev, FN_GET_STRIDE);
    g_num_planes = (u32_fn)g_dev->get_function(g_dev, FN_GET_NUM_FLEX_PLANES);
    g_lock_flex = (lock_flex_fn)g_dev->get_function(g_dev, FN_LOCK_FLEX);
    g_unlock = (unlock_fn)g_dev->get_function(g_dev, FN_UNLOCK);
    LOGI("gralloc1 open: dims %d format %d stride %d planes %d lock_flex %d unlock %d", !!g_dims, !!g_format,
         !!g_stride, !!g_num_planes, !!g_lock_flex, !!g_unlock);
}

int gr1_init(void) {
    pthread_once(&g_once, load);
    return g_dev && g_lock_flex && g_unlock && g_num_planes ? 0 : -ENODEV;
}

void gr1_describe(buffer_handle_t b) {
    if (gr1_init() != 0) return;
    uint32_t w = 0, h = 0, format = 0, stride = 0, planes = 0;
    int r1 = g_dims ? g_dims(g_dev, b, &w, &h) : -1, r2 = g_format ? g_format(g_dev, b, &format) : -1;
    int r3 = g_stride ? g_stride(g_dev, b, &stride) : -1, r4 = g_num_planes(g_dev, b, &planes);
    LOGI("gralloc1 buffer %p: %ux%u (%d) format 0x%x (%d) stride %u (%d) flex planes %u (%d)", b, w, h, r1, format,
         r2, stride, r3, planes, r4);
}

int gr1_lock_ycbcr(buffer_handle_t b, uint32_t w, uint32_t h, yuv_image_t *out) {
    if (gr1_init() != 0) return -ENODEV;
    uint32_t n = 0;
    if (g_num_planes(g_dev, b, &n) != 0 || n < 3 || n > MAX_PLANES) return -EINVAL;
    flex_plane_t planes[MAX_PLANES];
    memset(planes, 0, sizeof planes);
    flex_layout_t layout = {0, n, planes};
    gr1_rect_t all = {0, 0, (int32_t)w, (int32_t)h};
    if (g_lock_flex(g_dev, b, PRODUCER_CPU_WRITE_OFTEN, 0, &all, &layout, -1) != 0) return -EIO;
    int found = 0;
    for (uint32_t i = 0; i < layout.num_planes && i < n; ++i) {
        int k = planes[i].component == FLEX_Y ? 0 : planes[i].component == FLEX_CB ? 1
                : planes[i].component == FLEX_CR ? 2 : -1;
        if (k < 0) continue;
        out->plane[k] = (yuv_plane_t){planes[i].top_left, (uint32_t)planes[i].v_increment,
                                      (uint32_t)planes[i].h_increment};
        found |= 1 << k;
    }
    if (found != 7) {
        gr1_unlock(b);
        return -EINVAL;
    }
    return 0;
}

void gr1_unlock(buffer_handle_t b) {
    int32_t fence = -1;
    if (g_unlock && g_unlock(g_dev, b, &fence) == 0 && fence >= 0) close(fence);
}
