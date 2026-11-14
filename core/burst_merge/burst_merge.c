#include "instruments/burst_merge.h"

#include <stdlib.h>

static size_t luma_count(const burst_merge_t *m) { return (size_t)m->w * m->h; }
static size_t chroma_count(const burst_merge_t *m) { return (size_t)(m->w / 2) * (m->h / 2); }

static int size_ok(uint32_t w, uint32_t h) { return w > 0 && h > 0 && w % 2 == 0 && h % 2 == 0; }

int burst_merge_init(burst_merge_t *m, uint32_t w, uint32_t h) {
    if (m == NULL || !size_ok(w, h)) return BURST_MERGE_EINVAL;
    m->w = w;
    m->h = h;
    m->n = 0;
    m->sum = (uint32_t *)calloc(luma_count(m) + 2 * chroma_count(m), sizeof(uint32_t));
    return m->sum != NULL ? BURST_MERGE_OK : BURST_MERGE_ENOMEM;
}

static int frame_ok(const burst_merge_t *m, const burst_frame_t *f) {
    if (f == NULL || f->w != m->w || f->h != m->h) return 0;
    for (int p = 0; p < 3; ++p) {
        if (f->plane[p] == NULL) return 0;
        if (f->stride[p] < (p == 0 ? m->w : m->w / 2)) return 0;
    }
    return 1;
}

static void add_plane(uint32_t *sum, const uint8_t *src, uint32_t stride, uint32_t w, uint32_t h) {
    for (uint32_t r = 0; r < h; ++r) {
        const uint8_t *row = src + (size_t)r * stride;
        uint32_t *acc = sum + (size_t)r * w;
        for (uint32_t x = 0; x < w; ++x) acc[x] += row[x];
    }
}

int burst_merge_add(burst_merge_t *m, const burst_frame_t *f) {
    if (m == NULL || m->sum == NULL || !frame_ok(m, f)) return BURST_MERGE_EINVAL;
    if (m->n >= BURST_MERGE_MAX_FRAMES) return BURST_MERGE_EFULL;
    const uint32_t cw = m->w / 2, ch = m->h / 2;
    add_plane(m->sum, f->plane[0], f->stride[0], m->w, m->h);
    add_plane(m->sum + luma_count(m), f->plane[1], f->stride[1], cw, ch);
    add_plane(m->sum + luma_count(m) + chroma_count(m), f->plane[2], f->stride[2], cw, ch);
    m->n++;
    return BURST_MERGE_OK;
}

/* round(num / n) with ties up, computed exactly as floor((2 num + n) / (2 n)). */
static uint64_t round_div(uint64_t num, uint32_t n) { return (2 * num + n) / (2 * (uint64_t)n); }

static int finish_check(const burst_merge_t *m, const void *out) {
    if (m == NULL || m->sum == NULL || out == NULL) return BURST_MERGE_EINVAL;
    return m->n == 0 ? BURST_MERGE_EEMPTY : BURST_MERGE_OK;
}

int burst_merge_finish_y16(const burst_merge_t *m, uint16_t *y16, uint32_t stride) {
    int rc = finish_check(m, y16);
    if (rc != BURST_MERGE_OK) return rc;
    if (stride < m->w) return BURST_MERGE_EINVAL;
    for (uint32_t r = 0; r < m->h; ++r)
        for (uint32_t x = 0; x < m->w; ++x) {
            const uint64_t s = m->sum[(size_t)r * m->w + x];
            y16[(size_t)r * stride + x] = (uint16_t)round_div(256u * s, m->n);
        }
    return BURST_MERGE_OK;
}

int burst_merge_finish_i420(const burst_merge_t *m, uint8_t *out) {
    int rc = finish_check(m, out);
    if (rc != BURST_MERGE_OK) return rc;
    const size_t total = luma_count(m) + 2 * chroma_count(m);
    for (size_t i = 0; i < total; ++i) out[i] = (uint8_t)round_div(m->sum[i], m->n);
    return BURST_MERGE_OK;
}

void burst_merge_free(burst_merge_t *m) {
    if (m == NULL) return;
    free(m->sum);
    m->sum = NULL;
    m->n = 0;
}

int burst_frame_from_i420(const uint8_t *buf, uint32_t w, uint32_t h, burst_frame_t *out) {
    if (buf == NULL || out == NULL || !size_ok(w, h)) return BURST_MERGE_EINVAL;
    const size_t ys = (size_t)w * h, cs = (size_t)(w / 2) * (h / 2);
    out->plane[0] = buf;
    out->plane[1] = buf + ys;
    out->plane[2] = buf + ys + cs;
    out->stride[0] = w;
    out->stride[1] = w / 2;
    out->stride[2] = w / 2;
    out->w = w;
    out->h = h;
    return BURST_MERGE_OK;
}
