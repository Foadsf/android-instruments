/*
 * Minimal copies of the AOSP legacy camera HAL structures, for code built with the NDK (which
 * ships no libhardware headers). Layouts follow, field for field:
 *   hardware/libhardware/include/hardware/hardware.h       (hw_module_t, hw_module_methods_t)
 *   hardware/libhardware/include/hardware/camera_common.h  (camera_info, camera_module_t,
 *                                                           camera_module_callbacks_t)
 *   system/media/camera/include/system/camera_metadata.h   (camera_metadata_ro_entry_t)
 * A missing field here shifts every field after it; halprobe once crashed on exactly that.
 */
#ifndef INSTRUMENTS_LEGACY_CAMERA_HAL_H
#define INSTRUMENTS_LEGACY_CAMERA_HAL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define HAL_MAKE_TAG(a, b, c, d) (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(d))
#define HAL_HARDWARE_MODULE_TAG HAL_MAKE_TAG('H', 'W', 'M', 'T')
#define HAL_CAMERA_MODULE_API_VERSION_2_4 0x0204

struct hw_module_t;
typedef struct hw_device_t hw_device_t;

typedef struct hw_module_methods_t {
    int (*open)(const struct hw_module_t *module, const char *id, hw_device_t **device);
} hw_module_methods_t;

typedef struct hw_module_t {
    uint32_t tag;
    uint16_t module_api_version;
    uint16_t hal_api_version;
    const char *id;
    const char *name;
    const char *author;
    hw_module_methods_t *methods;
    void *dso;
#ifdef __LP64__
    uint64_t reserved[32 - 7];
#else
    uint32_t reserved[32 - 7];
#endif
} hw_module_t;

typedef struct camera_info {
    int facing;
    int orientation;
    uint32_t device_version;
    const void *static_camera_characteristics;
    int resource_cost;
    char **conflicting_devices;
    size_t conflicting_devices_length;
} camera_info_t;

typedef struct camera_module_callbacks {
    void (*camera_device_status_change)(const struct camera_module_callbacks *, int camera_id, int new_status);
    void (*torch_mode_status_change)(const struct camera_module_callbacks *, const char *camera_id, int new_status);
} camera_module_callbacks_t;

typedef struct camera_module {
    hw_module_t common;
    int (*get_number_of_cameras)(void);
    int (*get_camera_info)(int camera_id, struct camera_info *info);
    int (*set_callbacks)(const camera_module_callbacks_t *callbacks);
    void (*get_vendor_tag_ops)(void *ops);
    int (*open_legacy)(const hw_module_t *module, const char *id, uint32_t hal_version, hw_device_t **device);
    int (*set_torch_mode)(const char *camera_id, bool enabled);
    int (*init)(void);
    void *reserved[5];
} camera_module_t;

typedef struct camera_metadata_ro_entry {
    size_t index;
    uint32_t tag;
    uint8_t type;
    size_t count;
    union {
        const uint8_t *u8;
        const int32_t *i32;
        const float *f;
        const int64_t *i64;
        const double *d;
        const void *r;
    } data;
} camera_metadata_ro_entry_t;

#endif
