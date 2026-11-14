/* camera_metadata entry points, resolved at run time from libcamera_metadata.so. */
#ifndef INSTRUMENTS_CAMSHIM_BRIDGE_META_H
#define INSTRUMENTS_CAMSHIM_BRIDGE_META_H

#include "legacy_camera3.h"
#include "legacy_camera_hal.h"

typedef struct {
    camera_metadata_t *(*allocate)(size_t entries, size_t data);
    int (*add)(camera_metadata_t *m, uint32_t tag, const void *data, size_t count);
    int (*append)(camera_metadata_t *dst, const camera_metadata_t *src);
    size_t (*entry_count)(const camera_metadata_t *m);
    size_t (*data_count)(const camera_metadata_t *m);
    camera_metadata_t *(*clone)(const camera_metadata_t *m);
    void (*release)(camera_metadata_t *m);
    int (*find_ro)(const camera_metadata_t *m, uint32_t tag, camera_metadata_ro_entry_t *e);
} meta_api_t;

/* Returns 0 when every entry point resolved. */
int meta_load(meta_api_t *api);
/* Default request settings for a HAL3 template type; caller owns the result. */
camera_metadata_t *meta_build_default(const meta_api_t *api, int type);
/* settings plus ANDROID_SENSOR_TIMESTAMP; caller owns the result. settings may be NULL. */
camera_metadata_t *meta_build_result(const meta_api_t *api, const camera_metadata_t *settings, int64_t ts);

#endif
