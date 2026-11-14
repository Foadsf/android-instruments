#include "bridge_meta.h"

#include <dlfcn.h>

int meta_load(meta_api_t *a) {
    void *lib = dlopen("libcamera_metadata.so", RTLD_NOW);
    if (!lib) return -1;
    a->allocate = (camera_metadata_t * (*)(size_t, size_t)) dlsym(lib, "allocate_camera_metadata");
    a->add = (int (*)(camera_metadata_t *, uint32_t, const void *, size_t))dlsym(lib, "add_camera_metadata_entry");
    a->append = (int (*)(camera_metadata_t *, const camera_metadata_t *))dlsym(lib, "append_camera_metadata");
    a->entry_count = (size_t(*)(const camera_metadata_t *))dlsym(lib, "get_camera_metadata_entry_count");
    a->data_count = (size_t(*)(const camera_metadata_t *))dlsym(lib, "get_camera_metadata_data_count");
    a->clone = (camera_metadata_t * (*)(const camera_metadata_t *)) dlsym(lib, "clone_camera_metadata");
    a->release = (void (*)(camera_metadata_t *))dlsym(lib, "free_camera_metadata");
    a->find_ro = (int (*)(const camera_metadata_t *, uint32_t, camera_metadata_ro_entry_t *))dlsym(
        lib, "find_camera_metadata_ro_entry");
    return a->allocate && a->add && a->append && a->entry_count && a->data_count && a->clone && a->release &&
                   a->find_ro
               ? 0
               : -1;
}

camera_metadata_t *meta_build_default(const meta_api_t *a, int type) {
    camera_metadata_t *m = a->allocate(16, 128);
    if (!m) return NULL;
    uint8_t intent = (uint8_t)type, mode = 1 /* AUTO */, ae = 1 /* ON */, awb = 1 /* AUTO */;
    uint8_t af = type == 3 ? 3 /* CONTINUOUS_VIDEO */ : 4 /* CONTINUOUS_PICTURE */, antibanding = 3 /* AUTO */;
    int32_t fps[2] = {type == 3 ? 30 : 15, 30};
    a->add(m, TAG_CONTROL_CAPTURE_INTENT, &intent, 1);
    a->add(m, TAG_CONTROL_MODE, &mode, 1);
    a->add(m, TAG_CONTROL_AE_MODE, &ae, 1);
    a->add(m, TAG_CONTROL_AF_MODE, &af, 1);
    a->add(m, TAG_CONTROL_AWB_MODE, &awb, 1);
    a->add(m, TAG_CONTROL_AE_ANTIBANDING_MODE, &antibanding, 1);
    a->add(m, TAG_CONTROL_AE_TARGET_FPS_RANGE, fps, 2);
    return m;
}

camera_metadata_t *meta_build_result(const meta_api_t *a, const camera_metadata_t *settings, int64_t ts) {
    size_t entries = settings ? a->entry_count(settings) : 0, data = settings ? a->data_count(settings) : 0;
    camera_metadata_t *m = a->allocate(entries + 2, data + 32);
    if (!m) return NULL;
    camera_metadata_ro_entry_t e;
    if (settings && a->find_ro(settings, TAG_SENSOR_TIMESTAMP, &e) != 0) a->append(m, settings);
    a->add(m, TAG_SENSOR_TIMESTAMP, &ts, 1);
    return m;
}
