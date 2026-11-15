/*
 * Homography alignment of two 8-bit luma planes (docs/units/align.md, first revision).
 *
 * Finds H (3x3, h33 = 1, pixel coordinates, pixel centres at integers) and a gain g and offset o
 * such that M(H x) ~ g R(x) + o over the overlap. A pure translation by (dx, dy) means the content
 * moved right by dx in M. Method: Gaussian pyramid, integer search at the top level, then
 * inverse-compositional Lucas-Kanade (translation, similarity, homography from coarse to fine) with
 * a Huber weight and bicubic sampling of M. Pure C, no Android: tested on the host.
 */
#ifndef INSTRUMENTS_ALIGN_H
#define INSTRUMENTS_ALIGN_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ALIGN_OK 0
#define ALIGN_EINVAL (-1)      /* size mismatch, smaller than 64x64, NULL plane, short stride */
#define ALIGN_EUNTEXTURED (-2) /* < 500 textured samples, or a control-point standard error > 0.05 px */
#define ALIGN_EOVERLAP (-3)    /* the warped reference covers < 50 % of the moving frame */
#define ALIGN_ENOMEM (-4)

#define ALIGN_MODEL_TRANSLATION 2
#define ALIGN_MODEL_SIMILARITY 4
#define ALIGN_MODEL_HOMOGRAPHY 8

#define ALIGN_CONTROL_POINTS 5

typedef struct {
    double h[9];       /* row-major, h[8] == 1 */
    double gain, offset;
    double rms;        /* RMS residual in grey levels at the finest level */
    uint32_t samples;  /* sample pixels used at the finest level */
    int converged;     /* the finest level stopped on the 0.001 px rule */
    double overlap;    /* fraction of the reference grid that lands inside M */
    /* Control points: the centre, then the points a quarter of the width and height in from the
     * corners (top-left, top-right, bottom-left, bottom-right). Displacement H c - c and its
     * standard error per axis, in pixels. */
    double cp[ALIGN_CONTROL_POINTS][2];
    double cp_disp[ALIGN_CONTROL_POINTS][2];
    double cp_se[ALIGN_CONTROL_POINTS][2];
} align_result_t;

typedef struct {
    const double *h_init; /* 9 values or NULL (identity) */
    int max_model;        /* ALIGN_MODEL_*; 0 means homography */
} align_options_t;

/* Aligns M (mov) to R (ref). On a refusal the result holds what was measured (overlap, samples,
 * standard errors) but h is not to be used. */
int align_luma(const uint8_t *ref, uint32_t ref_stride, const uint8_t *mov, uint32_t mov_stride,
               uint32_t w, uint32_t h, const align_options_t *opts, align_result_t *out);

/* Maps (x, y) through a row-major homography. */
void align_apply(const double h[9], double x, double y, double *u, double *v);

#ifdef __cplusplus
}
#endif

#endif
