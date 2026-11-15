/* Internals of the align unit, shared by its C files and its tests. */
#ifndef INSTRUMENTS_ALIGN_INTERNAL_H
#define INSTRUMENTS_ALIGN_INTERNAL_H

#include <stdint.h>

typedef struct {
    float *data;
    int w, h;
} align_plane_t;

#define ALIGN_MAX_LEVELS 12

typedef struct {
    align_plane_t level[ALIGN_MAX_LEVELS];
    int n;
} align_pyramid_t;

/* align_image.c */
int align_plane_from_u8(const uint8_t *src, uint32_t stride, int w, int h, align_plane_t *out);
void align_plane_free(align_plane_t *p);
/* Levels until the short side would drop below min_side; level k pixel i sits at level 0 i * 2^k. */
int align_pyramid_build(const align_plane_t *base, int min_side, align_pyramid_t *out);
void align_pyramid_free(align_pyramid_t *p);
/* Bicubic (Keys, a = -0.5) sample at (x, y); needs 1 <= x <= w - 3 and likewise for y. With the
 * test-only build flag ALIGN_TEST_BILINEAR it samples bilinearly instead. */
float align_sample(const align_plane_t *p, double x, double y);
int align_sample_ok(const align_plane_t *p, double x, double y);

/* align_math.c */
void align_mat3_mul(const double a[9], const double b[9], double out[9]);
int align_mat3_inv(const double a[9], double out[9]);
void align_mat3_normalise(double h[9]);
/* H at level k from level 0 and back: S^-1 H S with S = diag(2^k, 2^k, 1). */
void align_to_level(const double h0[9], int k, double out[9]);
void align_from_level(const double hk[9], int k, double out[9]);
/* The pixel homography of an increment p of `model` parameters in coordinates normalised by
 * (x - cx) / s: translation (p0, p1); similarity (p0 scale, p1 rotation, p2, p3); homography
 * (p0 h11-1, p1 h21, p2 h12, p3 h22-1, p4 h13, p5 h23, p6 h31, p7 h32). */
void align_increment(const double *p, int model, double cx, double cy, double s, double out[9]);
/* Solves a x = b (n <= 10) with partial pivoting; returns 0, or -1 if singular. */
int align_solve(double *a, double *b, int n, double *x);
int align_invert_sym(const double *a, int n, double *out);

#endif
