/*
 * hal1probe: drive a vendor camera module through the legacy HAL1 interface and count preview
 * frames delivered by data callback (no preview window). Run as root with the camera provider
 * stopped, so no other process holds the sensor.
 *
 *   hal1probe <module.so> <camera_id> [seconds] [key=value ...]
 *
 * key=value pairs are applied to the HAL1 parameters before start_preview. One JSON object per
 * line on stdout. The first preview frame is written to /data/local/tmp/instruments/hal1_<id>.yuv.
 * Exit: 0 at least one preview frame, 1 opened but no frames, 3 could not open.
 */
#include <dlfcn.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#include "instruments/camera_params.h"
#include "legacy_camera_hal1.h"
#include "probe_window.h"

#define PARAMS_MAX 16384

static atomic_int g_frames, g_notify, g_errors;
static atomic_size_t g_last_size;
static int g_saved;
static char g_save_path[128];

typedef struct {
    camera_memory_t mem;
    int mapped; /* 1: mmap of an fd, 0: malloc */
} probe_memory_t;

static void release_memory(camera_memory_t *m) {
    probe_memory_t *pm = (probe_memory_t *)m;
    if (pm->mapped) munmap(m->data, m->size);
    else free(m->data);
    free(pm);
}

static camera_memory_t *request_memory(int fd, size_t buf_size, unsigned int num_bufs, void *user) {
    (void)user;
    probe_memory_t *pm = calloc(1, sizeof *pm);
    if (!pm) return NULL;
    pm->mem.size = buf_size * num_bufs;
    if (fd >= 0) {
        pm->mem.data = mmap(NULL, pm->mem.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        pm->mapped = 1;
        if (pm->mem.data == MAP_FAILED) pm->mem.data = NULL;
    } else {
        pm->mem.data = calloc(1, pm->mem.size);
    }
    if (!pm->mem.data) {
        free(pm);
        return NULL;
    }
    pm->mem.release = release_memory;
    return &pm->mem;
}

static void on_notify(int32_t msg, int32_t ext1, int32_t ext2, void *user) {
    (void)user;
    atomic_fetch_add(&g_notify, 1);
    if (msg == CAMERA_MSG_ERROR) atomic_fetch_add(&g_errors, 1);
    printf("{\"event\":\"notify\",\"msg\":%d,\"ext1\":%d,\"ext2\":%d}\n", msg, ext1, ext2);
    fflush(stdout);
}

static void save_once(const camera_memory_t *data, unsigned int index) {
    if (g_saved || !data || !data->data || !data->size) return;
    g_saved = 1;
    FILE *f = fopen(g_save_path, "wb");
    if (!f) return;
    size_t one = data->size; /* the HAL passes the whole heap; index selects a slot of unknown size */
    fwrite(data->data, 1, one, f);
    fclose(f);
    printf("{\"event\":\"saved\",\"path\":\"%s\",\"bytes\":%zu,\"index\":%u}\n", g_save_path, one, index);
}

static void on_data(int32_t msg, const camera_memory_t *data, unsigned int index, camera_frame_metadata_t *md,
                    void *user) {
    (void)md;
    (void)user;
    if (msg & CAMERA_MSG_PREVIEW_FRAME) {
        atomic_fetch_add(&g_frames, 1);
        if (data) atomic_store(&g_last_size, data->size);
        save_once(data, index);
    }
}

static void on_data_ts(int64_t ts, int32_t msg, const camera_memory_t *data, unsigned int index, void *user) {
    (void)ts;
    on_data(msg, data, index, NULL, user);
}

/* Module-level callbacks: the vendor HAL reports torch and device status through these during
 * open; leaving them unset crashed HAL_camera_device_open on a NULL read at offset 4. */
static void on_device_status(const camera_module_callbacks_t *cb, int id, int status) {
    (void)cb;
    printf("{\"event\":\"device_status\",\"id\":%d,\"status\":%d}\n", id, status);
}

static void on_torch_status(const camera_module_callbacks_t *cb, const char *id, int status) {
    (void)cb;
    printf("{\"event\":\"torch_status\",\"id\":\"%s\",\"status\":%d}\n", id ? id : "", status);
}

static const camera_module_callbacks_t g_module_callbacks = {on_device_status, on_torch_status};

static camera_device_t *open_hal1(camera_module_t *m, const char *id) {
    hw_device_t *dev = NULL;
    int rc = m->open_legacy ? m->open_legacy(&m->common, id, HAL_CAMERA_DEVICE_API_VERSION_1_0, &dev) : -38;
    printf("{\"event\":\"open_legacy\",\"id\":\"%s\",\"rc\":%d}\n", id, rc);
    fflush(stdout);
    return rc == 0 ? (camera_device_t *)dev : NULL;
}

/* Applies key=value overrides to the current parameters; returns set_parameters' result. */
static int apply_params(camera_device_t *d, int argc, char **argv) {
    char *cur = d->ops->get_parameters(d);
    static char a[PARAMS_MAX], b[PARAMS_MAX];
    snprintf(a, sizeof a, "%s", cur ? cur : "");
    if (cur && d->ops->put_parameters) d->ops->put_parameters(d, cur);
    char v[64];
    if (camera_params_get(a, "preview-size", v, sizeof v)) printf("{\"event\":\"param\",\"preview-size\":\"%s\"}\n", v);
    if (camera_params_get(a, "preview-format", v, sizeof v)) printf("{\"event\":\"param\",\"preview-format\":\"%s\"}\n", v);
    for (int i = 0; i < argc; ++i) {
        char key[96];
        const char *eq = strchr(argv[i], '=');
        if (!eq || (size_t)(eq - argv[i]) >= sizeof key) continue;
        memcpy(key, argv[i], (size_t)(eq - argv[i]));
        key[eq - argv[i]] = '\0';
        if (camera_params_set(a, key, eq + 1, b, sizeof b) < 0) continue;
        memcpy(a, b, sizeof a);
        printf("{\"event\":\"param_set\",\"key\":\"%s\",\"value\":\"%s\"}\n", key, eq + 1);
    }
    int rc = d->ops->set_parameters(d, a);
    printf("{\"event\":\"set_parameters\",\"rc\":%d}\n", rc);
    fflush(stdout);
    return rc;
}

static probe_window_t *g_window; /* set by --window: frames go to a preview window, not callbacks */

static int run(camera_device_t *d, const char *id, int seconds, int argc, char **argv) {
    snprintf(g_save_path, sizeof g_save_path, "/data/local/tmp/instruments/hal1_%s.yuv", id);
    d->ops->set_callbacks(d, on_notify, on_data, on_data_ts, request_memory, NULL);
    apply_params(d, argc, argv);
    if (g_window) {
        int wrc = d->ops->set_preview_window(d, probe_window_ops(g_window));
        printf("{\"event\":\"set_preview_window\",\"rc\":%d}\n", wrc);
        d->ops->enable_msg_type(d, CAMERA_MSG_ERROR);
    } else {
        d->ops->enable_msg_type(d, CAMERA_MSG_PREVIEW_FRAME | CAMERA_MSG_ERROR);
    }
    int rc = d->ops->start_preview(d);
    printf("{\"event\":\"start_preview\",\"rc\":%d}\n", rc);
    fflush(stdout);
    if (rc == 0) {
        for (int s = 1; s <= seconds; ++s) {
            sleep(1);
            printf("{\"event\":\"tick\",\"s\":%d,\"frames\":%d,\"window_frames\":%d,\"last_size\":%zu}\n", s,
                   atomic_load(&g_frames), g_window ? probe_window_frames(g_window) : 0, atomic_load(&g_last_size));
        }
        d->ops->stop_preview(d);
    }
    d->ops->release(d);
    d->common.close(&d->common);
    if (g_window) probe_window_report(g_window);
    int frames = g_window ? probe_window_frames(g_window) : atomic_load(&g_frames);
    printf("{\"event\":\"done\",\"frames\":%d,\"notifies\":%d,\"errors\":%d}\n", frames, atomic_load(&g_notify),
           atomic_load(&g_errors));
    return frames > 0 ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: hal1probe <module.so> <camera_id> [seconds] [key=value ...]\n");
        return 2;
    }
    setvbuf(stdout, NULL, _IONBF, 0); /* a HAL crash must not swallow buffered output */
    if (argc > 3 && strcmp(argv[argc - 1], "--window") == 0) {
        char path[128];
        snprintf(path, sizeof path, "/data/local/tmp/instruments/hal1win_%s.yuv", argv[2]);
        g_window = probe_window_create(path);
        --argc;
    }
    int seconds = argc > 3 && !strchr(argv[3], '=') ? atoi(argv[3]) : 3;
    int first_kv = argc > 3 && !strchr(argv[3], '=') ? 4 : 3;
    void *lib = dlopen(argv[1], RTLD_NOW);
    camera_module_t *m = lib ? (camera_module_t *)dlsym(lib, "HMI") : NULL;
    if (!m) {
        printf("{\"event\":\"load_failed\",\"error\":\"%s\"}\n", lib ? "no HMI" : dlerror());
        return 3;
    }
    if (m->init) m->init();
    if (m->set_callbacks) m->set_callbacks(&g_module_callbacks);
    printf("{\"event\":\"module\",\"name\":\"%s\",\"cameras\":%d}\n", m->common.name, m->get_number_of_cameras());
    camera_device_t *d = open_hal1(m, argv[2]);
    if (!d) return 3;
    return run(d, argv[2], seconds, argc - first_kv, argv + first_kv);
}
