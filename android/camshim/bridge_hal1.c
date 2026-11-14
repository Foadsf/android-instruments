#include "bridge_hal1.h"

#include <android/log.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/system_properties.h>

#include "bridge.h"

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "InstrumentsCameraBridge", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "InstrumentsCameraBridge", __VA_ARGS__)
#define PLUGIN_DIR_PROP "persist.instruments.camera.plugin_dir"

/* Samsung's fusion plugins are not on LineageOS; preloading them by absolute path satisfies the
 * HAL's later dlopen by name (their SONAMEs match the file names). */
void bridge_preload_plugins(void) {
    static const char *names[] = {"libdualcam_optical_zoom.so", "libdualpreview_interface.so",
                                  "libdualcapture_interface.so"};
    char dir[PROP_VALUE_MAX] = {0}, path[PROP_VALUE_MAX + 64];
    if (__system_property_get(PLUGIN_DIR_PROP, dir) <= 0) strcpy(dir, "/data/local/tmp/instruments/stocklib");
    for (size_t i = 0; i < sizeof names / sizeof names[0]; ++i) {
        snprintf(path, sizeof path, "%s/%s", dir, names[i]);
        void *h = dlopen(path, RTLD_NOW | RTLD_GLOBAL);
        LOGI("preload %s: %s", path, h ? "ok" : dlerror());
    }
}

static void on_notify(int32_t msg, int32_t e1, int32_t e2, void *u) {
    (void)u;
    if (msg == CAMERA_MSG_ERROR) LOGE("HAL1 error %d %d", e1, e2);
}

static void on_data(int32_t m, const camera_memory_t *d, unsigned int i, camera_frame_metadata_t *md, void *u) {
    (void)m, (void)d, (void)i, (void)md, (void)u;
}

static void on_data_ts(int64_t t, int32_t m, const camera_memory_t *d, unsigned int i, void *u) {
    (void)t, (void)m, (void)d, (void)i, (void)u;
}

static void mem_release(camera_memory_t *m) {
    if (m->handle) munmap(m->data, m->size);
    else free(m->data);
    free(m);
}

static camera_memory_t *on_memory(int fd, size_t size, unsigned int n, void *u) {
    (void)u;
    camera_memory_t *m = calloc(1, sizeof *m);
    if (!m) return NULL;
    m->size = size * n;
    m->data = fd >= 0 ? mmap(NULL, m->size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0) : calloc(1, m->size);
    m->handle = fd >= 0 ? m : NULL; /* non-NULL marks an mmap */
    if (!m->data || m->data == MAP_FAILED) {
        free(m);
        return NULL;
    }
    m->release = mem_release;
    return m;
}

void bridge_hal1_set_callbacks(camera_device_t *dev) {
    dev->ops->set_callbacks(dev, on_notify, on_data, on_data_ts, on_memory, NULL);
    dev->ops->enable_msg_type(dev, CAMERA_MSG_ERROR);
}
