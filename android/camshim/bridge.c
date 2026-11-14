#include "bridge.h"

#include <android/log.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/system_properties.h>
#include <unistd.h>

#include "bridge_hal1.h"
#include "bridge_internal.h"
#include "instruments/camera_params.h"

#define TAG "InstrumentsCameraBridge"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)
#define ZOOM_PROP "persist.instruments.camera.bridge_zoom"
#define FRAMEWORK_USAGE 0x33u /* CPU read and write often: the bridge copies into these buffers */

static bridge_t *of(const camera3_device_t *d) { return (bridge_t *)d; }

/* ---- delivering results in frame order ---------------------------------------------------- */

static void deliver_one(bridge_t *b, const bq_slot_t *s) {
    camera3_stream_buffer_t out = {b->stream, (buffer_handle_t *)s->buffer, CAMERA3_BUFFER_STATUS_OK, -1, -1};
    camera3_notify_msg_t msg;
    memset(&msg, 0, sizeof msg);
    camera3_capture_result_t r;
    memset(&r, 0, sizeof r);
    r.frame_number = s->frame;
    r.num_output_buffers = 1;
    r.output_buffers = &out;
    camera_metadata_t *meta = NULL;
    if (s->state == BQ_DONE) {
        msg.type = CAMERA3_MSG_SHUTTER;
        msg.message.shutter.frame_number = s->frame;
        msg.message.shutter.timestamp = (uint64_t)s->timestamp;
        b->cb->notify(b->cb, &msg);
        pthread_mutex_lock(&b->lock);
        meta = meta_build_result(&b->meta, b->last_settings, s->timestamp);
        pthread_mutex_unlock(&b->lock);
        r.result = meta;
        r.partial_result = (uint32_t)b->partial_count;
    } else {
        msg.type = CAMERA3_MSG_ERROR;
        msg.message.error.frame_number = s->frame;
        msg.message.error.error_code = CAMERA3_MSG_ERROR_REQUEST;
        b->cb->notify(b->cb, &msg);
        out.status = CAMERA3_BUFFER_STATUS_ERROR;
        if (s->fence >= 0) out.release_fence = s->fence; /* never waited: hand it back */
    }
    b->cb->process_capture_result(b->cb, &r);
    if (meta) b->meta.release(meta);
}

/* Pops everything ready (under the lock), then calls the framework without the lock held. */
void bridge_deliver_ready(bridge_t *b) {
    bq_slot_t ready[BQ_CAPACITY];
    int n = 0;
    pthread_mutex_lock(&b->lock);
    while (n < BQ_CAPACITY && bq_pop(&b->q, &ready[n])) ++n;
    pthread_mutex_unlock(&b->lock);
    for (int i = 0; i < n; ++i) deliver_one(b, &ready[i]);
}

/* ---- HAL1 parameters and preview control --------------------------------------------------- */

static int hal1_set(bridge_t *b, const char *key, const char *value) {
    static char cur[16384], out[16384];
    char *p = b->hal1->ops->get_parameters(b->hal1);
    snprintf(cur, sizeof cur, "%s", p ? p : "");
    if (p && b->hal1->ops->put_parameters) b->hal1->ops->put_parameters(b->hal1, p);
    if (camera_params_set(cur, key, value, out, sizeof out) < 0) return -EINVAL;
    return b->hal1->ops->set_parameters(b->hal1, out);
}

/* Caller holds ctl. Stops HAL1 preview, fails what is still in flight and returns it. */
static void stop_preview(bridge_t *b) {
    pthread_mutex_lock(&b->lock);
    int was = b->previewing;
    b->previewing = 0;
    pthread_mutex_unlock(&b->lock);
    if (was) b->hal1->ops->stop_preview(b->hal1);
    pthread_mutex_lock(&b->lock);
    bq_fail_all(&b->q);
    pthread_mutex_unlock(&b->lock);
    bridge_deliver_ready(b);
}

/* 1 if "WxH" is one of the comma-separated preview-size-values. */
static int size_supported(bridge_t *b, uint32_t w, uint32_t h) {
    static char values[4096];
    char *p = b->hal1->ops->get_parameters(b->hal1);
    int found = p && camera_params_get(p, "preview-size-values", values, sizeof values);
    if (p && b->hal1->ops->put_parameters) b->hal1->ops->put_parameters(b->hal1, p);
    if (!found) return 0;
    char want[32];
    int n = snprintf(want, sizeof want, "%ux%u", w, h);
    for (const char *s = values; (s = strstr(s, want)) != NULL; s += n)
        if ((s == values || s[-1] == ',') && (s[n] == ',' || s[n] == '\0')) return 1;
    LOGE("preview size %s not in %s", want, values);
    return 0;
}

/* ---- camera3 device ops -------------------------------------------------------------------- */

static int b_initialize(const camera3_device_t *d, const camera3_callback_ops_t *cb) {
    of(d)->cb = cb;
    return 0;
}

static int b_configure(const camera3_device_t *d, camera3_stream_configuration_t *list) {
    bridge_t *b = of(d);
    if (!list || list->num_streams != 1 || !list->streams || !list->streams[0]) return -EINVAL;
    camera3_stream_t *s = list->streams[0];
    if (s->stream_type != CAMERA3_STREAM_OUTPUT ||
        (s->format != HAL_PIXEL_FORMAT_YCBCR_420_888 && s->format != HAL_PIXEL_FORMAT_IMPLEMENTATION_DEFINED))
        return -EINVAL;
    pthread_mutex_lock(&b->ctl);
    stop_preview(b);
    char size[32];
    snprintf(size, sizeof size, "%ux%u", s->width, s->height);
    int rc = size_supported(b, s->width, s->height) ? hal1_set(b, "preview-size", size) : -EINVAL;
    if (rc == 0) rc = b->hal1->ops->set_preview_window(b->hal1, &b->window.ops);
    if (rc == 0) {
        s->usage |= FRAMEWORK_USAGE;
        s->max_buffers = 6;
        b->stream = s;
    }
    pthread_mutex_unlock(&b->ctl);
    LOGI("configure %s format 0x%x usage 0x%llx max %u space 0x%x rot %d phys %p op %u: %d", size, s->format,
         (unsigned long long)s->usage,
         s->max_buffers, s->data_space, s->rotation, (const void *)s->physical_camera_id, list->operation_mode, rc);
    return rc;
}

static const camera_metadata_t *b_defaults(const camera3_device_t *d, int type) {
    bridge_t *b = of(d);
    if (type < 1 || type >= MAX_TEMPLATES) return NULL;
    pthread_mutex_lock(&b->lock);
    if (!b->defaults[type]) b->defaults[type] = meta_build_default(&b->meta, type);
    const camera_metadata_t *m = b->defaults[type];
    pthread_mutex_unlock(&b->lock);
    return m;
}

/* start_preview takes a few hundred ms (both sensors, buffer set-up): keep it off the request thread. */
static void *starter_main(void *arg) {
    bridge_t *b = arg;
    pthread_mutex_lock(&b->ctl);
    int rc = b->hal1->ops->start_preview(b->hal1);
    LOGI("start_preview: %d", rc);
    pthread_mutex_lock(&b->lock);
    b->previewing = rc == 0;
    b->starting = 0;
    pthread_mutex_unlock(&b->lock);
    if (rc != 0) stop_preview(b); /* fail and return what is queued */
    pthread_mutex_unlock(&b->ctl);
    return NULL;
}

static int b_request(const camera3_device_t *d, camera3_capture_request_t *r) {
    bridge_t *b = of(d);
    if (!r || r->input_buffer || r->num_output_buffers != 1 || !b->stream) return -EINVAL;
    const camera3_stream_buffer_t *o = &r->output_buffers[0];
    if (o->stream != b->stream) return -EINVAL;
    camera_metadata_t *fresh = r->settings ? b->meta.clone(r->settings) : NULL, *old = NULL;
    pthread_mutex_lock(&b->lock);
    if (fresh) {
        old = b->last_settings;
        b->last_settings = fresh;
    }
    int rc = bq_push(&b->q, r->frame_number, (void *)o->buffer, o->acquire_fence);
    int kick = rc == 0 && !b->previewing && !b->starting;
    if (kick) b->starting = 1;
    pthread_mutex_unlock(&b->lock);
    if (old) b->meta.release(old);
    if (rc != 0) return -EBUSY;
    if (kick) { /* only this thread and close touch starter; a previous starter has finished */
        if (b->starter_valid) pthread_join(b->starter, NULL);
        b->starter_valid = pthread_create(&b->starter, NULL, starter_main, b) == 0;
        if (!b->starter_valid) return -ENODEV;
    }
    return 0;
}

static void b_dump(const camera3_device_t *d, int fd) {
    bridge_t *b = of(d);
    pthread_mutex_lock(&b->lock);
    dprintf(fd, "instruments bridge: previewing=%d pending=%d copied=%d dropped=%d failed=%d\n", b->previewing,
            bq_count_state(&b->q, BQ_PENDING), b->stats[0], b->stats[1], b->stats[2]);
    pthread_mutex_unlock(&b->lock);
}

static int b_flush(const camera3_device_t *d) {
    bridge_t *b = of(d);
    pthread_mutex_lock(&b->ctl);
    stop_preview(b);
    pthread_mutex_unlock(&b->ctl);
    return 0;
}

static int b_close(hw_device_t *dev) {
    bridge_t *b = (bridge_t *)dev;
    if (b->starter_valid) pthread_join(b->starter, NULL);
    b_flush(&b->dev);
    b->hal1->ops->release(b->hal1);
    b->hal1->common.close(&b->hal1->common);
    bridge_window_stop(b);
    pool_destroy(b->pool);
    LOGI("closing: copied %d, dropped %d, copy failed %d", b->stats[0], b->stats[1], b->stats[2]);
    for (int i = 0; i < MAX_TEMPLATES; ++i)
        if (b->defaults[i]) b->meta.release(b->defaults[i]);
    if (b->last_settings) b->meta.release(b->last_settings);
    pthread_mutex_destroy(&b->lock);
    pthread_mutex_destroy(&b->ctl);
    free(b);
    LOGI("closed");
    return 0;
}

/* ---- opening ------------------------------------------------------------------------------- */

static void init_tables(bridge_t *b) {
    static camera3_device_ops_t ops = {.initialize = b_initialize, .configure_streams = b_configure,
                                       .construct_default_request_settings = b_defaults,
                                       .process_capture_request = b_request, .dump = b_dump, .flush = b_flush};
    b->dev.common.tag = HAL_HARDWARE_DEVICE_TAG;
    b->dev.common.version = HAL_CAMERA_DEVICE_API_VERSION_3_4;
    b->dev.common.close = b_close;
    b->ops = ops;
    b->dev.ops = &b->ops;
    pthread_mutex_init(&b->lock, NULL);
    pthread_mutex_init(&b->ctl, NULL);
    bq_init(&b->q);
    bridge_window_init(b);
    b->partial_count = 1;
}

int bridge_open(camera_module_t *vendor, const hw_module_t *module, const camera_metadata_t *static_info,
                hw_device_t **device) {
    bridge_t *b = calloc(1, sizeof *b);
    if (b) b->pool = pool_create();
    if (!b || !b->pool || meta_load(&b->meta) != 0 || !vendor->open_legacy) {
        if (b) pool_destroy(b->pool);
        free(b);
        return -ENODEV;
    }
    hw_device_t *dev = NULL;
    int rc = vendor->open_legacy(&vendor->common, "20", HAL_CAMERA_DEVICE_API_VERSION_1_0, &dev);
    LOGI("open_legacy(\"20\"): %d", rc);
    if (rc != 0 || !dev) {
        pool_destroy(b->pool);
        free(b);
        return rc ? rc : -ENODEV;
    }
    init_tables(b);
    b->dev.common.module = (struct hw_module_t *)module;
    b->hal1 = (camera_device_t *)dev;
    bridge_hal1_set_callbacks(b->hal1);
    char zoom[PROP_VALUE_MAX] = {0};
    if (__system_property_get(ZOOM_PROP, zoom) <= 0) strcpy(zoom, "30");
    LOGI("zoom=%s: %d", zoom, hal1_set(b, "zoom", zoom));
    camera_metadata_ro_entry_t e;
    if (static_info && b->meta.find_ro(static_info, TAG_REQUEST_PARTIAL_RESULT_COUNT, &e) == 0 && e.count == 1)
        b->partial_count = e.data.i32[0];
    *device = &b->dev.common;
    return 0;
}
