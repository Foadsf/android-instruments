/*
 * Minimal copies of the AOSP HAL1 camera device structures (hardware/libhardware/include/
 * hardware/camera.h, hardware.h; system/core/include/system/camera.h), field for field, for
 * NDK-built tools. Complements legacy_camera_hal.h (module side).
 */
#ifndef INSTRUMENTS_LEGACY_CAMERA_HAL1_H
#define INSTRUMENTS_LEGACY_CAMERA_HAL1_H

#include <stddef.h>
#include <stdint.h>

#include "legacy_camera_hal.h"

#define HAL_CAMERA_DEVICE_API_VERSION_1_0 0x100
#define HAL_HARDWARE_DEVICE_TAG HAL_MAKE_TAG('H', 'W', 'D', 'T')

/* camera message types (system/camera.h) */
#define CAMERA_MSG_ERROR 0x0001
#define CAMERA_MSG_SHUTTER 0x0002
#define CAMERA_MSG_FOCUS 0x0004
#define CAMERA_MSG_ZOOM 0x0008
#define CAMERA_MSG_PREVIEW_FRAME 0x0010
#define CAMERA_MSG_VIDEO_FRAME 0x0020
#define CAMERA_MSG_PREVIEW_METADATA 0x0400

struct hw_device_t {
    uint32_t tag;
    uint32_t version;
    struct hw_module_t *module;
#ifdef __LP64__
    uint64_t reserved[12];
#else
    uint32_t reserved[12];
#endif
    int (*close)(struct hw_device_t *device);
};

typedef struct camera_memory {
    void *data;
    size_t size;
    void *handle;
    void (*release)(struct camera_memory *mem);
} camera_memory_t;

typedef struct camera_frame_metadata camera_frame_metadata_t; /* opaque here */

typedef void (*camera_notify_callback)(int32_t msg_type, int32_t ext1, int32_t ext2, void *user);
typedef void (*camera_data_callback)(int32_t msg_type, const camera_memory_t *data, unsigned int index,
                                     camera_frame_metadata_t *metadata, void *user);
typedef void (*camera_data_timestamp_callback)(int64_t timestamp, int32_t msg_type, const camera_memory_t *data,
                                               unsigned int index, void *user);
typedef camera_memory_t *(*camera_request_memory)(int fd, size_t buf_size, unsigned int num_bufs, void *user);

struct camera_device;
struct preview_stream_ops; /* opaque: hal1probe passes NULL or does not call set_preview_window */

typedef struct camera_device_ops {
    int (*set_preview_window)(struct camera_device *, struct preview_stream_ops *window);
    void (*set_callbacks)(struct camera_device *, camera_notify_callback notify_cb, camera_data_callback data_cb,
                          camera_data_timestamp_callback data_cb_timestamp, camera_request_memory get_memory,
                          void *user);
    void (*enable_msg_type)(struct camera_device *, int32_t msg_type);
    void (*disable_msg_type)(struct camera_device *, int32_t msg_type);
    int (*msg_type_enabled)(struct camera_device *, int32_t msg_type);
    int (*start_preview)(struct camera_device *);
    void (*stop_preview)(struct camera_device *);
    int (*preview_enabled)(struct camera_device *);
    int (*store_meta_data_in_buffers)(struct camera_device *, int enable);
    int (*start_recording)(struct camera_device *);
    void (*stop_recording)(struct camera_device *);
    int (*recording_enabled)(struct camera_device *);
    void (*release_recording_frame)(struct camera_device *, const void *opaque);
    int (*auto_focus)(struct camera_device *);
    int (*cancel_auto_focus)(struct camera_device *);
    int (*take_picture)(struct camera_device *);
    int (*cancel_picture)(struct camera_device *);
    int (*set_parameters)(struct camera_device *, const char *parms);
    char *(*get_parameters)(struct camera_device *);
    void (*put_parameters)(struct camera_device *, char *);
    int (*send_command)(struct camera_device *, int32_t cmd, int32_t arg1, int32_t arg2);
    void (*release)(struct camera_device *);
    int (*dump)(struct camera_device *, int fd);
} camera_device_ops_t;

typedef struct camera_device {
    struct hw_device_t common;
    camera_device_ops_t *ops;
    void *priv;
} camera_device_t;

#endif
