#include "instruments/camera_params.h"

#include <string.h>

/* Finds "key=" at the start of an entry; returns a pointer to the entry or NULL. */
static const char *find_entry(const char *params, const char *key) {
    size_t klen = strlen(key);
    const char *p = params;
    while (p && *p) {
        if (strncmp(p, key, klen) == 0 && p[klen] == '=') return p;
        p = strchr(p, ';');
        if (p) ++p;
    }
    return NULL;
}

int camera_params_get(const char *params, const char *key, char *out, size_t n) {
    if (n == 0) return 0;
    out[0] = '\0';
    const char *e = params ? find_entry(params, key) : NULL;
    if (!e) return 0;
    const char *v = e + strlen(key) + 1;
    size_t len = strcspn(v, ";");
    if (len >= n) len = n - 1;
    memcpy(out, v, len);
    out[len] = '\0';
    return 1;
}

static int append(char *out, size_t n, size_t *pos, const char *s, size_t len) {
    if (*pos + len + 1 > n) return -1;
    memcpy(out + *pos, s, len);
    *pos += len;
    out[*pos] = '\0';
    return 0;
}

int camera_params_set(const char *params, const char *key, const char *value, char *out, size_t n) {
    if (strpbrk(key, "=;") || strpbrk(value, "=;") || n == 0) return -1;
    size_t pos = 0;
    out[0] = '\0';
    const char *src = params ? params : "";
    const char *e = find_entry(src, key);
    size_t klen = strlen(key), vlen = strlen(value);
    if (e) {
        const char *after = e + klen + 1 + strcspn(e + klen + 1, ";");
        if (append(out, n, &pos, src, (size_t)(e - src)) || append(out, n, &pos, key, klen) ||
            append(out, n, &pos, "=", 1) || append(out, n, &pos, value, vlen) ||
            append(out, n, &pos, after, strlen(after)))
            return -1;
        return (int)pos;
    }
    size_t slen = strlen(src);
    int need_sep = slen > 0 && src[slen - 1] != ';';
    if (append(out, n, &pos, src, slen) || (need_sep && append(out, n, &pos, ";", 1)) ||
        append(out, n, &pos, key, klen) || append(out, n, &pos, "=", 1) || append(out, n, &pos, value, vlen))
        return -1;
    return (int)pos;
}
