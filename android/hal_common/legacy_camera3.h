/*
 * Minimal copies of the AOSP HAL3 device structures (hardware/libhardware/include/hardware/
 * camera3.h, device version 3.4/3.5 layouts) and the camera_metadata entry points used by the
 * bridge, field for field, for NDK-built code.
 */
#ifndef INSTRUMENTS_LEGACY_CAMERA3_H
#define INSTRUMENTS_LEGACY_CAMERA3_H

#include <stddef.h>
#include <stdint.h>

#include "legacy_camera_hal1.h"

#define HAL_CAMERA_DEVICE_API_VERSION_3_4 0x304
#define CAMERA3_STREAM_OUTPUT 0
#define CAMERA3_BUFFER_STATUS_OK 0
#define CAMERA3_BUFFER_STATUS_ERROR 1
#define CAMERA3_MSG_ERROR 1
#define CAMERA3_MSG_SHUTTER 2
#define CAMERA3_MSG_ERROR_REQUEST 2
#define HAL_PIXEL_FORMAT_IMPLEMENTATION_DEFINED 0x22
#define HAL_PIXEL_FORMAT_YCBCR_420_888 0x23

typedef struct camera_metadata camera_metadata_t;

typedef struct camera3_stream {
    int stream_type;
    uint32_t width;
    uint32_t height;
    int format;
    /* 64-bit: measured on the Note8's LineageOS 20 provider (words 4-5 of the struct held the
     * consumer usage, word 6 max_buffers, word 8 data_space). A uint32_t here shifts every later field. */
    uint64_t usage;
    uint32_t max_buffers;
    void *priv;
    int data_space;
    int rotation;
    const char *physical_camera_id;
    void *reserved[6];
} camera3_stream_t;

typedef struct camera3_stream_configuration {
    uint32_t num_streams;
    camera3_stream_t **streams;
    uint32_t operation_mode;
    const camera_metadata_t *session_parameters;
} camera3_stream_configuration_t;

typedef struct camera3_stream_buffer {
    camera3_stream_t *stream;
    buffer_handle_t *buffer;
    int status;
    int acquire_fence;
    int release_fence;
} camera3_stream_buffer_t;

typedef struct camera3_capture_request {
    uint32_t frame_number;
    const camera_metadata_t *settings;
    camera3_stream_buffer_t *input_buffer;
    uint32_t num_output_buffers;
    const camera3_stream_buffer_t *output_buffers;
    uint32_t num_physcam_settings;
    const char **physcam_id;
    const camera_metadata_t **physcam_settings;
} camera3_capture_request_t;

typedef struct camera3_capture_result {
    uint32_t frame_number;
    const camera_metadata_t *result;
    uint32_t num_output_buffers;
    const camera3_stream_buffer_t *output_buffers;
    const camera3_stream_buffer_t *input_buffer;
    uint32_t partial_result;
    uint32_t num_physcam_metadata;
    const char **physcam_ids;
    const camera_metadata_t **physcam_metadata;
} camera3_capture_result_t;

typedef struct camera3_notify_msg {
    int type;
    union {
        struct { uint32_t frame_number; camera3_stream_t *error_stream; int error_code; } error;
        struct { uint32_t frame_number; uint64_t timestamp; } shutter;
        uint8_t generic[32];
    } message;
} camera3_notify_msg_t;

typedef struct camera3_callback_ops {
    void (*process_capture_result)(const struct camera3_callback_ops *, const camera3_capture_result_t *result);
    void (*notify)(const struct camera3_callback_ops *, const camera3_notify_msg_t *msg);
} camera3_callback_ops_t;

struct camera3_device;
typedef struct camera3_device_ops {
    int (*initialize)(const struct camera3_device *, const camera3_callback_ops_t *callback_ops);
    int (*configure_streams)(const struct camera3_device *, camera3_stream_configuration_t *stream_list);
    int (*register_stream_buffers)(const struct camera3_device *, const void *buffer_set);
    const camera_metadata_t *(*construct_default_request_settings)(const struct camera3_device *, int type);
    int (*process_capture_request)(const struct camera3_device *, camera3_capture_request_t *request);
    void (*get_metadata_vendor_tag_ops)(const struct camera3_device *, void *ops);
    void (*dump)(const struct camera3_device *, int fd);
    int (*flush)(const struct camera3_device *);
    void *reserved[8];
} camera3_device_ops_t;

typedef struct camera3_device {
    struct hw_device_t common;
    camera3_device_ops_t *ops;
    void *priv;
} camera3_device_t;

/* system/media/camera tags used by the bridge */
#define TAG_CONTROL_AE_ANTIBANDING_MODE 0x10000u
#define TAG_CONTROL_AE_MODE 0x10003u
#define TAG_CONTROL_AE_TARGET_FPS_RANGE 0x10005u
#define TAG_CONTROL_AF_MODE 0x10007u
#define TAG_CONTROL_AWB_MODE 0x1000Bu
#define TAG_CONTROL_CAPTURE_INTENT 0x1000Du
#define TAG_CONTROL_MODE 0x1000Fu
#define TAG_REQUEST_PARTIAL_RESULT_COUNT 0xC000Bu
#define TAG_SENSOR_TIMESTAMP 0xE0010u

#endif
