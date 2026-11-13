/*
 * halprobe: ask a legacy camera HAL module directly how many cameras it has and what each one
 * is, bypassing the camera service and any wrapper. Read-only: it never opens a camera device.
 *
 *   halprobe <module.so> [id ...]      (default ids: 0-7 20-23 50-53, the Samsung candidates)
 *
 * Prints one JSON object. Exit 0 when the module loaded, 3 when it could not be loaded.
 * Struct layouts follow AOSP hardware/libhardware include/hardware/{hardware,camera_common}.h.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct hw_module_t {
    uint32_t tag;
    uint16_t module_api_version;
    uint16_t hal_api_version;
    const char *id;
    const char *name;
    const char *author;
    void *methods;
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

typedef struct camera_module {
    hw_module_t common;
    int (*get_number_of_cameras)(void);
    int (*get_camera_info)(int camera_id, struct camera_info *info);
    int (*set_callbacks)(const void *callbacks);
    void (*get_vendor_tag_ops)(void *ops);
    int (*open_legacy)(const hw_module_t *module, const char *id, uint32_t hal_version, void **device);
    int (*set_torch_mode)(const char *camera_id, int enabled);
    int (*init)(void);
    void *reserved[5];
} camera_module_t;

typedef struct {
    uint32_t tag;
    uint8_t type;
    size_t count;
    union { const uint8_t *u8; const int32_t *i32; const float *f; const int64_t *i64; const double *d; const void *r; } data;
} metadata_entry_t;

typedef int (*find_entry_fn)(const void *meta, uint32_t tag, metadata_entry_t *entry);
typedef size_t (*count_fn)(const void *meta);

#define TAG_LENS_FACING 0x80005u
#define TAG_FOCAL_LENGTHS 0x90002u
#define TAG_MIN_FOCUS 0x90005u
#define TAG_PHYSICAL_SIZE 0xf0005u
#define TAG_PIXEL_ARRAY 0xf0006u

static void print_floats(const char *key, find_entry_fn find, const void *meta, uint32_t tag) {
    metadata_entry_t e;
    printf(", \"%s\": ", key);
    if (find == NULL || meta == NULL || find(meta, tag, &e) != 0) {
        printf("null");
        return;
    }
    printf("[");
    for (size_t k = 0; k < e.count; ++k) printf("%s%g", k ? ", " : "", (double)e.data.f[k]);
    printf("]");
}

static void print_ints(const char *key, find_entry_fn find, const void *meta, uint32_t tag) {
    metadata_entry_t e;
    printf(", \"%s\": ", key);
    if (find == NULL || meta == NULL || find(meta, tag, &e) != 0) {
        printf("null");
        return;
    }
    printf("[");
    for (size_t k = 0; k < e.count; ++k) printf("%s%d", k ? ", " : "", (int)e.data.i32[k]);
    printf("]");
}

static void probe_id(const camera_module_t *m, int id, int first, find_entry_fn find, count_fn count) {
    camera_info_t info;
    memset(&info, 0, sizeof info);
    printf("%s\n    {\"id\": %d", first ? "" : ",", id);
    fflush(stdout); /* if the HAL crashes on this id, the output still names it */
    int rc = m->get_camera_info(id, &info);
    printf(", \"rc\": %d", rc);
    if (rc == 0) {
        const void *meta = info.static_camera_characteristics;
        printf(", \"facing\": %d, \"orientation\": %d, \"device_version\": \"0x%x\", \"metadata_entries\": %zu",
               info.facing, info.orientation, info.device_version, (meta && count) ? count(meta) : (size_t)0);
        print_floats("focal_lengths_mm", find, meta, TAG_FOCAL_LENGTHS);
        print_floats("min_focus_diopters", find, meta, TAG_MIN_FOCUS);
        print_floats("physical_size_mm", find, meta, TAG_PHYSICAL_SIZE);
        print_ints("pixel_array", find, meta, TAG_PIXEL_ARRAY);
    }
    printf("}");
    fflush(stdout);
}

int main(int argc, char **argv) {
    static const int default_ids[] = {0, 1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23, 50, 51, 52, 53};
    if (argc < 2) {
        fprintf(stderr, "usage: halprobe <camera module .so> [id ...]\n");
        return 2;
    }
    int n_ids = argc > 2 ? argc - 2 : (int)(sizeof default_ids / sizeof default_ids[0]);
    void *meta_lib = dlopen("libcamera_metadata.so", RTLD_NOW);
    find_entry_fn find = meta_lib ? (find_entry_fn)dlsym(meta_lib, "find_camera_metadata_ro_entry") : NULL;
    count_fn count = meta_lib ? (count_fn)dlsym(meta_lib, "get_camera_metadata_entry_count") : NULL;
    void *lib = dlopen(argv[1], RTLD_NOW);
    if (lib == NULL) {
        printf("{\"module\": \"%s\", \"loaded\": false, \"error\": \"%s\"}\n", argv[1], dlerror());
        return 3;
    }
    const camera_module_t *m = (const camera_module_t *)dlsym(lib, "HMI");
    if (m == NULL) {
        printf("{\"module\": \"%s\", \"loaded\": true, \"error\": \"no HMI symbol\"}\n", argv[1]);
        return 3;
    }
    if (m->init) m->init();
    printf("{\"module\": \"%s\", \"name\": \"%s\", \"module_api_version\": \"0x%x\", "
           "\"get_number_of_cameras\": %d, \"cameras\": [",
           argv[1], m->common.name ? m->common.name : "", m->common.module_api_version,
           m->get_number_of_cameras());
    fflush(stdout);
    for (int k = 0; k < n_ids; ++k) {
        int id = argc > 2 ? atoi(argv[2 + k]) : default_ids[k];
        probe_id(m, id, k == 0, find, count);
    }
    printf("\n]}\n");
    return 0;
}
