/* Planes, the Gaussian pyramid and sub-pixel sampling for the align unit (docs/units/align.md).
 * REDUCE is ported from android-microscope Pyramid.kt: the 5-tap binomial [1 4 6 4 1]/16, then
 * every second sample, so level-k pixel i sits at level-0 coordinate i * 2^k. */
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "align_internal.h"

static const float K0 = 0.375f, K1 = 0.25f, K2 = 0.0625f;

static int clampi(int i, int n) { return i < 0 ? 0 : (i >= n ? n - 1 : i); }

int align_plane_from_u8(const uint8_t *src, uint32_t stride, int w, int h, align_plane_t *out) {
    out->data = (float *)malloc(sizeof(float) * (size_t)w * (size_t)h);
    if (!out->data) return -1;
    out->w = w;
    out->h = h;
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) out->data[(size_t)y * w + x] = (float)src[(size_t)y * stride + x];
    return 0;
}

void align_plane_free(align_plane_t *p) {
    free(p->data);
    p->data = NULL;
    p->w = p->h = 0;
}

static int reduce(const align_plane_t *p, align_plane_t *out) {
    const int w = p->w, h = p->h, w2 = (w + 1) / 2, h2 = (h + 1) / 2;
    float *tmp = (float *)malloc(sizeof(float) * (size_t)w2 * (size_t)h);
    out->data = (float *)malloc(sizeof(float) * (size_t)w2 * (size_t)h2);
    if (!tmp || !out->data) {
        free(tmp);
        free(out->data);
        out->data = NULL;
        return -1;
    }
    for (int y = 0; y < h; ++y) {
        const float *d = p->data + (size_t)y * w;
        for (int x2 = 0; x2 < w2; ++x2) {
            const int x = 2 * x2;
            tmp[(size_t)y * w2 + x2] = K0 * d[x] + K1 * (d[clampi(x - 1, w)] + d[clampi(x + 1, w)]) +
                                       K2 * (d[clampi(x - 2, w)] + d[clampi(x + 2, w)]);
        }
    }
    for (int y2 = 0; y2 < h2; ++y2) {
        const int y = 2 * y2;
        const float *r0 = tmp + (size_t)y * w2, *rm1 = tmp + (size_t)clampi(y - 1, h) * w2;
        const float *rp1 = tmp + (size_t)clampi(y + 1, h) * w2, *rm2 = tmp + (size_t)clampi(y - 2, h) * w2;
        const float *rp2 = tmp + (size_t)clampi(y + 2, h) * w2;
        for (int x = 0; x < w2; ++x)
            out->data[(size_t)y2 * w2 + x] = K0 * r0[x] + K1 * (rm1[x] + rp1[x]) + K2 * (rm2[x] + rp2[x]);
    }
    free(tmp);
    out->w = w2;
    out->h = h2;
    return 0;
}

int align_pyramid_build(const align_plane_t *base, int min_side, align_pyramid_t *out) {
    memset(out, 0, sizeof *out);
    out->level[0] = *base; /* borrowed: not freed by align_pyramid_free */
    out->n = 1;
    while (out->n < ALIGN_MAX_LEVELS) {
        const align_plane_t *last = &out->level[out->n - 1];
        const int side = last->w < last->h ? last->w : last->h;
        if (side / 2 < min_side) break;
        if (reduce(last, &out->level[out->n]) != 0) return -1;
        out->n++;
    }
    return 0;
}

void align_pyramid_free(align_pyramid_t *p) {
    for (int k = 1; k < p->n; ++k) align_plane_free(&p->level[k]);
    p->n = 0;
}

int align_sample_ok(const align_plane_t *p, double x, double y) {
    return x >= 1.0 && y >= 1.0 && x <= p->w - 3.0 && y <= p->h - 3.0;
}

#ifdef ALIGN_TEST_BILINEAR
float align_sample(const align_plane_t *p, double x, double y) {
    const int x0 = (int)floor(x), y0 = (int)floor(y);
    const float fx = (float)(x - x0), fy = (float)(y - y0);
    const float *r = p->data + (size_t)y0 * p->w + x0;
    return (r[0] * (1 - fx) + r[1] * fx) * (1 - fy) + (r[p->w] * (1 - fx) + r[p->w + 1] * fx) * fy;
}
#else
static void keys_weights(double t, double wgt[4]) {
    /* Keys cubic convolution, a = -0.5, for the taps at -1, 0, 1, 2 from the integer part. */
    const double a = -0.5, t2 = t * t, t3 = t2 * t;
    wgt[0] = a * (t3 - 2 * t2 + t);
    wgt[1] = (a + 2) * t3 - (a + 3) * t2 + 1;
    wgt[2] = -(a + 2) * t3 + (2 * a + 3) * t2 - a * t;
    wgt[3] = -a * (t3 - t2);
}

float align_sample(const align_plane_t *p, double x, double y) {
    const int x0 = (int)floor(x), y0 = (int)floor(y);
    double wx[4], wy[4], acc = 0.0;
    keys_weights(x - x0, wx);
    keys_weights(y - y0, wy);
    for (int j = 0; j < 4; ++j) {
        const float *r = p->data + (size_t)(y0 - 1 + j) * p->w + (x0 - 1);
        acc += wy[j] * (wx[0] * r[0] + wx[1] * r[1] + wx[2] * r[2] + wx[3] * r[3]);
    }
    return (float)acc;
}
#endif
