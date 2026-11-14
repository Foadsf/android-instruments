/*
 * Camera HAL shim that exposes vendor cameras the vendor HAL answers for but does not count.
 *
 * Built as camera.<board>.so, it replaces LineageOS's pass-through "Zero Camera Wrapper" and
 * keeps its two behaviours (load the module registered as camera.vendor, disable fdsan for the
 * Samsung blob). On top it reports get_number_of_cameras() + extra IDs and maps framework IDs
 * to vendor IDs both ways (core/camera_idmap). On the Note8 (LineageOS 20) Samsung HAL ID 3 is
 * the telephoto, so framework camera 2 becomes the telephoto.
 *
 * Extra IDs come from persist.instruments.camera.extra_ids (default "3"); an ID is kept only if
 * the vendor HAL's get_camera_info answers for it. Device objects are the vendor's own, passed
 * through unchanged; the vendor device reports HAL 3.4 itself.
 */
#include <android/fdsan.h>
#include <android/log.h>
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/system_properties.h>

#include "instruments/camera_idmap.h"
#include "legacy_camera_hal.h"

#define TAG "InstrumentsCameraShim"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)
#define EXTRA_IDS_PROP "persist.instruments.camera.extra_ids"
#define DEFAULT_EXTRA_IDS "3"
#ifdef __LP64__
#define VENDOR_FALLBACK_PATH "/system/lib64/hw/camera.vendor.universal8895.so"
#else
#define VENDOR_FALLBACK_PATH "/system/lib/hw/camera.vendor.universal8895.so"
#endif

typedef int (*hw_get_module_by_class_fn)(const char *, const char *, const hw_module_t **);

static camera_module_t *g_vendor;
static camera_idmap_t g_map;
static int g_map_ready;
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static const camera_module_callbacks_t *g_framework_callbacks;

static camera_module_t *load_vendor(void) {
    void *libhw = dlopen("libhardware.so", RTLD_NOW);
    hw_get_module_by_class_fn get = libhw ? (hw_get_module_by_class_fn)dlsym(libhw, "hw_get_module_by_class") : NULL;
    const hw_module_t *mod = NULL;
    if (get != NULL && get("camera", "vendor", &mod) == 0 && mod != NULL) return (camera_module_t *)mod;
    void *lib = dlopen(VENDOR_FALLBACK_PATH, RTLD_NOW);
    if (lib == NULL) {
        LOGE("cannot load the vendor camera module: %s", dlerror());
        return NULL;
    }
    return (camera_module_t *)dlsym(lib, "HMI");
}

/* Loads the vendor module and builds the ID map once; 0 on success. */
static int ensure_ready(void) {
    pthread_mutex_lock(&g_lock);
    if (g_vendor == NULL) {
        android_fdsan_set_error_level(ANDROID_FDSAN_ERROR_LEVEL_DISABLED);
        g_vendor = load_vendor();
    }
    if (g_vendor != NULL && !g_map_ready) {
        char ids[PROP_VALUE_MAX] = {0};
        if (__system_property_get(EXTRA_IDS_PROP, ids) <= 0) strcpy(ids, DEFAULT_EXTRA_IDS);
        camera_idmap_init(&g_map, g_vendor->get_number_of_cameras(), ids);
        for (int k = g_map.n_extra - 1; k >= 0; --k) {
            camera_info_t info;
            memset(&info, 0, sizeof info);
            int rc = g_vendor->get_camera_info(g_map.extra_vendor_ids[k], &info);
            LOGI("extra vendor camera %d: get_camera_info rc=%d facing=%d", g_map.extra_vendor_ids[k], rc, info.facing);
            if (rc != 0) camera_idmap_remove_extra(&g_map, k);
        }
        g_map_ready = 1;
        LOGI("vendor counts %d cameras; exposing %d", g_map.vendor_count, camera_idmap_count(&g_map));
    }
    int ok = g_vendor != NULL && g_map_ready;
    pthread_mutex_unlock(&g_lock);
    return ok ? 0 : -ENODEV;
}

/* Framework camera name ("2") -> vendor camera name ("3"); 0 on success. */
static int map_name(const char *framework_name, char *out, size_t n) {
    if (framework_name == NULL) return -EINVAL;
    char *end = NULL;
    long id = strtol(framework_name, &end, 10);
    if (end == framework_name || *end != '\0') return -EINVAL;
    int vendor_id = camera_idmap_to_vendor(&g_map, (int)id);
    if (vendor_id < 0) return -EINVAL;
    snprintf(out, n, "%d", vendor_id);
    return 0;
}

static void on_status_change(const camera_module_callbacks_t *cb, int vendor_id, int status) {
    (void)cb;
    int fw = camera_idmap_to_framework(&g_map, vendor_id);
    if (fw >= 0 && g_framework_callbacks && g_framework_callbacks->camera_device_status_change)
        g_framework_callbacks->camera_device_status_change(g_framework_callbacks, fw, status);
}

static void on_torch_change(const camera_module_callbacks_t *cb, const char *vendor_name, int status) {
    (void)cb;
    char *end = NULL;
    long vendor_id = vendor_name ? strtol(vendor_name, &end, 10) : -1;
    int fw = (end != vendor_name && end && *end == '\0') ? camera_idmap_to_framework(&g_map, (int)vendor_id) : -1;
    if (fw < 0 || !g_framework_callbacks || !g_framework_callbacks->torch_mode_status_change) return;
    char name[16];
    snprintf(name, sizeof name, "%d", fw);
    g_framework_callbacks->torch_mode_status_change(g_framework_callbacks, name, status);
}

static const camera_module_callbacks_t g_shim_callbacks = {on_status_change, on_torch_change};

static int shim_open(const hw_module_t *module, const char *name, hw_device_t **device) {
    (void)module;
    char vendor_name[16];
    if (ensure_ready() != 0 || map_name(name, vendor_name, sizeof vendor_name) != 0) return -EINVAL;
    int rc = g_vendor->common.methods->open(&g_vendor->common, vendor_name, device);
    LOGI("open framework camera %s -> vendor camera %s: %d", name, vendor_name, rc);
    return rc;
}

static int shim_get_number_of_cameras(void) { return ensure_ready() == 0 ? camera_idmap_count(&g_map) : 0; }

static int shim_get_camera_info(int camera_id, camera_info_t *info) {
    if (ensure_ready() != 0) return -ENODEV;
    int vendor_id = camera_idmap_to_vendor(&g_map, camera_id);
    return vendor_id < 0 ? -EINVAL : g_vendor->get_camera_info(vendor_id, info);
}

static int shim_set_callbacks(const camera_module_callbacks_t *callbacks) {
    if (ensure_ready() != 0) return -ENODEV;
    g_framework_callbacks = callbacks;
    return g_vendor->set_callbacks ? g_vendor->set_callbacks(&g_shim_callbacks) : 0;
}

static void shim_get_vendor_tag_ops(void *ops) {
    if (ensure_ready() == 0 && g_vendor->get_vendor_tag_ops) g_vendor->get_vendor_tag_ops(ops);
}

static int shim_open_legacy(const hw_module_t *module, const char *id, uint32_t hal_version, hw_device_t **device) {
    (void)module;
    char vendor_name[16];
    if (ensure_ready() != 0 || map_name(id, vendor_name, sizeof vendor_name) != 0) return -EINVAL;
    if (g_vendor->open_legacy == NULL) return -ENOSYS;
    return g_vendor->open_legacy(&g_vendor->common, vendor_name, hal_version, device);
}

static int shim_set_torch_mode(const char *camera_id, bool enabled) {
    char vendor_name[16];
    if (ensure_ready() != 0 || map_name(camera_id, vendor_name, sizeof vendor_name) != 0) return -EINVAL;
    return g_vendor->set_torch_mode ? g_vendor->set_torch_mode(vendor_name, enabled) : -ENOSYS;
}

static int shim_init(void) {
    pthread_mutex_lock(&g_lock);
    if (g_vendor == NULL) {
        android_fdsan_set_error_level(ANDROID_FDSAN_ERROR_LEVEL_DISABLED);
        g_vendor = load_vendor();
    }
    camera_module_t *v = g_vendor;
    pthread_mutex_unlock(&g_lock);
    if (v == NULL) return -ENODEV;
    return v->init ? v->init() : 0;
}

static hw_module_methods_t g_methods = {shim_open};

__attribute__((visibility("default"))) camera_module_t HMI = {
    .common = {
        .tag = HAL_HARDWARE_MODULE_TAG,
        .module_api_version = HAL_CAMERA_MODULE_API_VERSION_2_4,
        .hal_api_version = 0,
        .id = "camera",
        .name = "Instruments Camera Shim (exposes uncounted vendor cameras)",
        .author = "android-instruments",
        .methods = &g_methods,
    },
    .get_number_of_cameras = shim_get_number_of_cameras,
    .get_camera_info = shim_get_camera_info,
    .set_callbacks = shim_set_callbacks,
    .get_vendor_tag_ops = shim_get_vendor_tag_ops,
    .open_legacy = shim_open_legacy,
    .set_torch_mode = shim_set_torch_mode,
    .init = shim_init,
};
