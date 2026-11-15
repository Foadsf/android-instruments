/* Homography alignment (docs/units/align.md, first revision). Ported from android-microscope
 * Align.kt (coarseSearch, refine, refineHomography): integer search at the top pyramid level, then
 * inverse-compositional Lucas-Kanade (Baker & Matthews 2004) with a Huber weight. Changes from the
 * port: a gain and offset fitted per iteration instead of an offset only; bicubic sampling; the
 * model raised translation -> similarity -> homography from coarse to fine; standard errors at
 * five control points; refusals for untextured scenes and small overlaps. */
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "align_internal.h"
#include "instruments/align.h"

#define MIN_SIDE 48
#define SEARCH_RADIUS 10
#define HUBER_K 12.0
#define MAX_SAMPLES_LOW 30000
#define MAX_SAMPLES_HIGH 60000
#define MIN_TEXTURED 500
#define TEXTURE_NOISE_FACTOR 4.0
#define SE_LIMIT 0.05
#define STOP_PX 0.001
#define MIN_OVERLAP 0.5

typedef struct {
    int *xs, *ys;
    float *tv, *iv;
    double *sd; /* np per sample */
    double *gmag;
    int n, np;
} samples_t;

typedef struct {
    double hess[64]; /* Huber-weighted, np x np, from the last iteration */
    double sigma2, rms, gain, offset;
    int used, converged;
} fit_t;

static void samples_free(samples_t *s) {
    free(s->xs); free(s->ys); free(s->tv); free(s->iv); free(s->sd); free(s->gmag);
    memset(s, 0, sizeof *s);
}

static void steepest(double gx, double gy, double xn, double yn, int model, double *o) {
    if (model == ALIGN_MODEL_TRANSLATION) {
        o[0] = gx; o[1] = gy;
    } else if (model == ALIGN_MODEL_SIMILARITY) {
        o[0] = gx * xn + gy * yn; o[1] = -gx * yn + gy * xn; o[2] = gx; o[3] = gy;
    } else {
        const double r = gx * xn + gy * yn;
        o[0] = gx * xn; o[1] = gy * xn; o[2] = gx * yn; o[3] = gy * yn;
        o[4] = gx; o[5] = gy; o[6] = -xn * r; o[7] = -yn * r;
    }
}

/* Samples on a stride grid with a gradient above 1 grey level; steepest-descent images at p = 0 in
 * coordinates normalised by s about the level centre. */
static int build_samples(const align_plane_t *t, int model, samples_t *out) {
    const int w = t->w, h = t->h, maxs = model == ALIGN_MODEL_HOMOGRAPHY ? MAX_SAMPLES_HIGH : MAX_SAMPLES_LOW;
    const int stride = (int)fmax(1.0, floor(sqrt((double)w * h / maxs)));
    const double cx = (w - 1) / 2.0, cy = (h - 1) / 2.0, s = (w > h ? w : h) / 2.0;
    const size_t cap = (size_t)((w / stride + 1) * (h / stride + 1));
    memset(out, 0, sizeof *out);
    out->np = model;
    out->xs = malloc(cap * sizeof(int)); out->ys = malloc(cap * sizeof(int));
    out->tv = malloc(cap * sizeof(float)); out->iv = malloc(cap * sizeof(float));
    out->sd = malloc(cap * (size_t)model * sizeof(double)); out->gmag = malloc(cap * sizeof(double));
    if (!out->xs || !out->ys || !out->tv || !out->iv || !out->sd || !out->gmag) return -1;
    for (int y = 2; y < h - 2; y += stride) {
        for (int x = 2; x < w - 2; x += stride) {
            const float *p = t->data + (size_t)y * w + x;
            const double gx = 0.5 * (p[1] - p[-1]), gy = 0.5 * (p[w] - p[-w]);
            if (gx * gx + gy * gy <= 1.0) continue;
            const int i = out->n++;
            out->xs[i] = x; out->ys[i] = y; out->tv[i] = p[0]; out->gmag[i] = sqrt(gx * gx + gy * gy);
            steepest(gx * s, gy * s, (x - cx) / s, (y - cy) / s, model, out->sd + (size_t)i * model);
        }
    }
    return 0;
}

static void control_points(int w, int h, double cp[5][2]) {
    const double xs[5] = {(w - 1) / 2.0, (w - 1) / 4.0, 3 * (w - 1) / 4.0, (w - 1) / 4.0, 3 * (w - 1) / 4.0};
    const double ys[5] = {(h - 1) / 2.0, (h - 1) / 4.0, (h - 1) / 4.0, 3 * (h - 1) / 4.0, 3 * (h - 1) / 4.0};
    for (int i = 0; i < 5; ++i) { cp[i][0] = xs[i]; cp[i][1] = ys[i]; }
}

/* Samples M under H; fits I = g T + o; returns the number of samples inside M. */
static int gather(const samples_t *s, const align_plane_t *m, const double h[9], int *inside, fit_t *f) {
    double st = 0, si = 0, stt = 0, sti = 0;
    int used = 0;
    for (int i = 0; i < s->n; ++i) {
        double u, v;
        align_apply(h, s->xs[i], s->ys[i], &u, &v);
        inside[i] = align_sample_ok(m, u, v);
        if (!inside[i]) continue;
        const double iv = align_sample(m, u, v), tv = s->tv[i];
        s->iv[i] = (float)iv;
        st += tv; si += iv; stt += tv * tv; sti += tv * iv;
        ++used;
    }
    const double den = used * stt - st * st;
    f->gain = (used > 2 && den > 0) ? (used * sti - st * si) / den : 1.0;
    if (!(f->gain > 0.2 && f->gain < 5.0)) f->gain = 1.0;
    f->offset = used > 0 ? (si - f->gain * st) / used : 0.0;
    return used;
}

/* One Gauss-Newton step: accumulates the weighted Hessian and solves for the increment. */
static int lk_step(const samples_t *s, const int *inside, fit_t *f, double *dp) {
    const int np = s->np;
    double b[8] = {0}, a[64], e2 = 0;
    memset(f->hess, 0, sizeof f->hess);
    for (int i = 0; i < s->n; ++i) {
        if (!inside[i]) continue;
        const double e = (s->iv[i] - f->offset) / f->gain - s->tv[i];
        const double rw = fabs(e) <= HUBER_K ? 1.0 : HUBER_K / fabs(e);
        const double *sd = s->sd + (size_t)i * np;
        for (int r = 0; r < np; ++r) {
            b[r] += rw * sd[r] * e;
            for (int c = r; c < np; ++c) f->hess[r * np + c] += rw * sd[r] * sd[c];
        }
        e2 += e * e;
    }
    for (int r = 0; r < np; ++r)
        for (int c = 0; c < r; ++c) f->hess[r * np + c] = f->hess[c * np + r];
    f->rms = sqrt(e2 / f->used);
    f->sigma2 = e2 / (f->used - np - 2 > 1 ? f->used - np - 2 : 1);
    memcpy(a, f->hess, sizeof(double) * (size_t)(np * np));
    return align_solve(a, b, np, dp);
}

/* Inverse-compositional refinement on one level; H in that level's pixels. */
static int refine(const align_plane_t *t, const align_plane_t *m, int model, int iters, int level,
                  double h[9], fit_t *f) {
    samples_t s;
    int rc = build_samples(t, model, &s);
    int *inside = rc == 0 ? malloc(sizeof(int) * (size_t)(s.n > 0 ? s.n : 1)) : NULL;
    const double cx = (t->w - 1) / 2.0, cy = (t->h - 1) / 2.0, sc = (t->w > t->h ? t->w : t->h) / 2.0;
    double cp[5][2];
    control_points(t->w, t->h, cp);
    f->converged = 0;
    for (int it = 0; rc == 0 && inside && it < iters && s.n >= 4 * model; ++it) {
        double dp[8], inc[9], inv[9];
        f->used = gather(&s, m, h, inside, f);
        if (f->used < 4 * model || lk_step(&s, inside, f, dp) != 0) break;
        align_increment(dp, model, cx, cy, sc, inc);
        if (align_mat3_inv(inc, inv) != 0) break;
        align_mat3_mul(h, inv, h);
        align_mat3_normalise(h);
        double move = 0;
        for (int k = 0; k < 5; ++k) {
            double u, v;
            align_apply(inc, cp[k][0], cp[k][1], &u, &v);
            move = fmax(move, fmax(fabs(u - cp[k][0]), fabs(v - cp[k][1])));
        }
        if (ldexp(move, level) < STOP_PX) { f->converged = 1; break; }
    }
    if (!inside) rc = ALIGN_ENOMEM;
    free(inside);
    samples_free(&s);
    return rc;
}

/* Zero-mean NCC of R against M under H on a sparse grid; -2 if the overlap is under a third. */
static double ncc(const align_plane_t *t, const align_plane_t *m, const double h[9]) {
    const int stride = (int)fmax(1.0, floor(sqrt(t->w * (double)t->h / 4000.0)));
    double st = 0, si = 0, stt = 0, sii = 0, sti = 0;
    int n = 0;
    for (int y = 0; y < t->h; y += stride)
        for (int x = 0; x < t->w; x += stride) {
            double u, v;
            align_apply(h, x, y, &u, &v);
            if (!align_sample_ok(m, u, v)) continue;
            const double a = t->data[(size_t)y * t->w + x], b = align_sample(m, u, v);
            st += a; si += b; stt += a * a; sii += b * b; sti += a * b;
            ++n;
        }
    if (n == 0 || (double)n * stride * stride < t->w * (double)t->h / 3.0) return -2.0;
    const double va = stt - st * st / n, vb = sii - si * si / n;
    return va > 0 && vb > 0 ? (sti - st * si / n) / sqrt(va * vb) : -2.0;
}

/* Exhaustive integer translation x scale search at the top level, about the starting guess. Scale
 * 1 is tried first and wins ties. */
static void coarse_search(const align_plane_t *t, const align_plane_t *m, double h[9]) {
    static const double scales[5] = {1.0, 0.95, 1.05, 0.90, 1.10};
    const double cx = (m->w - 1) / 2.0, cy = (m->h - 1) / 2.0;
    double best[9], score = -3.0;
    memcpy(best, h, sizeof best);
    for (int k = 0; k < 5; ++k) {
        const double sc = scales[k];
        for (int dy = -SEARCH_RADIUS; dy <= SEARCH_RADIUS; ++dy)
            for (int dx = -SEARCH_RADIUS; dx <= SEARCH_RADIUS; ++dx) {
                const double tr[9] = {sc, 0, cx * (1 - sc) + dx, 0, sc, cy * (1 - sc) + dy, 0, 0, 1};
                double cand[9];
                align_mat3_mul(tr, h, cand);
                const double c = ncc(t, m, cand);
                if (c > score) { score = c; memcpy(best, cand, sizeof best); }
            }
    }
    memcpy(h, best, sizeof best);
}

static double overlap(const double h[9], int w, int hh) {
    int in = 0;
    for (int j = 0; j < 32; ++j)
        for (int i = 0; i < 32; ++i) {
            double u, v;
            align_apply(h, (w - 1) * (i + 0.5) / 32.0, (hh - 1) * (j + 0.5) / 32.0, &u, &v);
            in += u >= 0 && v >= 0 && u <= w - 1 && v <= hh - 1;
        }
    return in / 1024.0;
}

/* Control-point displacements and their standard errors from the last fit's covariance. */
static int control_point_errors(const double h[9], int w, int hh, int model, const fit_t *f, align_result_t *out) {
    double cov[64], jac[2][8];
    const double cx = (w - 1) / 2.0, cy = (hh - 1) / 2.0, sc = (w > hh ? w : hh) / 2.0, eps = 1e-6;
    if (align_invert_sym(f->hess, model, cov) != 0) return -1;
    control_points(w, hh, out->cp);
    for (int k = 0; k < 5; ++k) {
        double u0, v0;
        align_apply(h, out->cp[k][0], out->cp[k][1], &u0, &v0);
        out->cp_disp[k][0] = u0 - out->cp[k][0];
        out->cp_disp[k][1] = v0 - out->cp[k][1];
        for (int j = 0; j < model; ++j) {
            double p[8] = {0}, inc[9], inv[9], hj[9], u, v;
            p[j] = eps;
            align_increment(p, model, cx, cy, sc, inc);
            align_mat3_inv(inc, inv);
            align_mat3_mul(h, inv, hj);
            align_apply(hj, out->cp[k][0], out->cp[k][1], &u, &v);
            jac[0][j] = (u - u0) / eps;
            jac[1][j] = (v - v0) / eps;
        }
        for (int a = 0; a < 2; ++a) {
            double var = 0;
            for (int r = 0; r < model; ++r)
                for (int c = 0; c < model; ++c) var += jac[a][r] * cov[r * model + c] * jac[a][c];
            out->cp_se[k][a] = sqrt(fmax(var, 0.0) * f->sigma2);
        }
    }
    return 0;
}

/* Textured samples at level 0: gradient above TEXTURE_NOISE_FACTOR x the noise gradient, which is
 * estimated from the fit residual (residual RMS ~ sqrt(2) sigma, gradient noise ~ sigma / sqrt(2)). */
static int textured_count(const align_plane_t *t, double rms) {
    samples_t s;
    int n = 0;
    const double thr = fmax(1.0, TEXTURE_NOISE_FACTOR * rms / 2.0);
    if (build_samples(t, ALIGN_MODEL_TRANSLATION, &s) == 0)
        for (int i = 0; i < s.n; ++i) n += s.gmag[i] > thr;
    samples_free(&s);
    return n;
}

static int model_at(int level, int top, int max_model) {
    const int m = level == top ? ALIGN_MODEL_TRANSLATION : (level >= 2 ? ALIGN_MODEL_SIMILARITY : ALIGN_MODEL_HOMOGRAPHY);
    return m < max_model ? m : max_model;
}

static int run_pyramid(const align_pyramid_t *pr, const align_pyramid_t *pm, const align_options_t *o,
                       double h0[9], fit_t *f, int *last_model) {
    const int top = (pr->n < pm->n ? pr->n : pm->n) - 1;
    const int maxm = (o && o->max_model) ? o->max_model : ALIGN_MODEL_HOMOGRAPHY;
    double init[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1}, h[9];
    if (o && o->h_init) memcpy(init, o->h_init, sizeof init);
    align_mat3_normalise(init);
    align_to_level(init, top, h);
    coarse_search(&pr->level[top], &pm->level[top], h);
    for (int k = top; k >= 0; --k) {
        *last_model = model_at(k, top, maxm);
        const int rc = refine(&pr->level[k], &pm->level[k], *last_model, k == top ? 30 : 10, k, h, f);
        if (rc != 0) return rc;
        if (k > 0) align_from_level(h, 1, h);
    }
    memcpy(h0, h, sizeof h);
    return 0;
}

int align_luma(const uint8_t *ref, uint32_t ref_stride, const uint8_t *mov, uint32_t mov_stride,
               uint32_t w, uint32_t h, const align_options_t *opts, align_result_t *out) {
    if (!ref || !mov || !out || w < 64 || h < 64 || ref_stride < w || mov_stride < w) return ALIGN_EINVAL;
    memset(out, 0, sizeof *out);
    align_plane_t r = {0}, m = {0};
    align_pyramid_t pr = {0}, pm = {0};
    fit_t f;
    memset(&f, 0, sizeof f);
    int model = ALIGN_MODEL_TRANSLATION, rc = ALIGN_ENOMEM;
    if (align_plane_from_u8(ref, ref_stride, (int)w, (int)h, &r) == 0 &&
        align_plane_from_u8(mov, mov_stride, (int)w, (int)h, &m) == 0 &&
        align_pyramid_build(&r, MIN_SIDE, &pr) == 0 && align_pyramid_build(&m, MIN_SIDE, &pm) == 0)
        rc = run_pyramid(&pr, &pm, opts, out->h, &f, &model);
    if (rc == 0) {
        out->gain = f.gain; out->offset = f.offset; out->rms = f.rms;
        out->samples = (uint32_t)f.used; out->converged = f.converged;
        out->overlap = overlap(out->h, (int)w, (int)h);
        if (control_point_errors(out->h, (int)w, (int)h, model, &f, out) != 0) rc = ALIGN_EUNTEXTURED;
        double se = 0;
        for (int k = 0; k < 5; ++k) se = fmax(se, fmax(out->cp_se[k][0], out->cp_se[k][1]));
        if (rc == 0 && (textured_count(&r, f.rms) < MIN_TEXTURED || !(se <= SE_LIMIT))) rc = ALIGN_EUNTEXTURED;
        if (rc == 0 && out->overlap < MIN_OVERLAP) rc = ALIGN_EOVERLAP;
    }
    align_pyramid_free(&pr);
    align_pyramid_free(&pm);
    align_plane_free(&r);
    align_plane_free(&m);
    return rc;
}
