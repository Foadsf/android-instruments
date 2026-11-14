#include "instruments/yuv_copy.h"

#include <stddef.h>
#include <string.h>

static int plane_ok(const yuv_plane_t *p, uint32_t width) {
    return p->data && p->pixel_stride > 0 && p->row_stride >= (width - 1) * p->pixel_stride + 1;
}

/* One plane of width x height samples, sample by sample unless both sides are packed. */
static void copy_plane(const yuv_plane_t *s, const yuv_plane_t *d, uint32_t width, uint32_t height) {
    for (uint32_t y = 0; y < height; ++y) {
        const uint8_t *sr = s->data + (size_t)y * s->row_stride;
        uint8_t *dr = d->data + (size_t)y * d->row_stride;
        if (s->pixel_stride == 1 && d->pixel_stride == 1) {
            memcpy(dr, sr, width);
            continue;
        }
        for (uint32_t x = 0; x < width; ++x) dr[(size_t)x * d->pixel_stride] = sr[(size_t)x * s->pixel_stride];
    }
}

/* Both sides interleave U and V the same way (pixel stride 2, same V-U offset): rows copy whole. */
static int same_interleave(const yuv_image_t *s, const yuv_image_t *d) {
    const yuv_plane_t *su = &s->plane[1], *sv = &s->plane[2], *du = &d->plane[1], *dv = &d->plane[2];
    ptrdiff_t so = sv->data - su->data, dof = dv->data - du->data;
    return su->pixel_stride == 2 && sv->pixel_stride == 2 && du->pixel_stride == 2 && dv->pixel_stride == 2 &&
           (so == 1 || so == -1) && so == dof && su->row_stride == sv->row_stride && du->row_stride == dv->row_stride;
}

int yuv420_copy(const yuv_image_t *src, const yuv_image_t *dst, uint32_t w, uint32_t h) {
    if (!src || !dst || w == 0 || h == 0 || (w & 1) || (h & 1)) return -1;
    for (int p = 0; p < 3; ++p) {
        uint32_t width = p ? w / 2 : w;
        if (!plane_ok(&src->plane[p], width) || !plane_ok(&dst->plane[p], width)) return -1;
    }
    copy_plane(&src->plane[0], &dst->plane[0], w, h);
    if (same_interleave(src, dst)) {
        int v_first = src->plane[2].data < src->plane[1].data;
        const yuv_plane_t *s = &src->plane[v_first ? 2 : 1], *d = &dst->plane[v_first ? 2 : 1];
        yuv_plane_t sp = {s->data, s->row_stride, 1}, dp = {d->data, d->row_stride, 1};
        copy_plane(&sp, &dp, w, h / 2); /* w/2 pairs = w bytes per row */
        return 0;
    }
    copy_plane(&src->plane[1], &dst->plane[1], w / 2, h / 2);
    copy_plane(&src->plane[2], &dst->plane[2], w / 2, h / 2);
    return 0;
}
