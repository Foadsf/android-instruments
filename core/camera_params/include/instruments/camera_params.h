/*
 * HAL1 CameraParameters strings ("k1=v1;k2=v2"): get one value, set one value (replace or
 * append). Pure C, no Android: tested on the host.
 */
#ifndef INSTRUMENTS_CAMERA_PARAMS_H
#define INSTRUMENTS_CAMERA_PARAMS_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Copies the value of key into out (size n, always NUL-terminated); returns 1 if found. */
int camera_params_get(const char *params, const char *key, char *out, size_t n);

/* Writes params with key set to value into out (size n). Returns the length written, or -1 if
 * out is too small or key/value contain '=' or ';'. */
int camera_params_set(const char *params, const char *key, const char *value, char *out, size_t n);

#ifdef __cplusplus
}
#endif

#endif
