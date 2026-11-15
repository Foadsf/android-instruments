/* 3x3 homography algebra and small linear solves for the align unit (docs/units/align.md). */
#include <math.h>
#include <string.h>

#include "align_internal.h"
#include "instruments/align.h"

void align_mat3_mul(const double a[9], const double b[9], double out[9]) {
    double r[9];
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) r[3 * i + j] = a[3 * i] * b[j] + a[3 * i + 1] * b[3 + j] + a[3 * i + 2] * b[6 + j];
    memcpy(out, r, sizeof r);
}

int align_mat3_inv(const double a[9], double out[9]) {
    const double c00 = a[4] * a[8] - a[5] * a[7], c01 = a[5] * a[6] - a[3] * a[8], c02 = a[3] * a[7] - a[4] * a[6];
    const double det = a[0] * c00 + a[1] * c01 + a[2] * c02;
    if (!(fabs(det) > 1e-300)) return -1;
    const double r[9] = {c00 / det, (a[2] * a[7] - a[1] * a[8]) / det, (a[1] * a[5] - a[2] * a[4]) / det,
                         c01 / det, (a[0] * a[8] - a[2] * a[6]) / det, (a[2] * a[3] - a[0] * a[5]) / det,
                         c02 / det, (a[1] * a[6] - a[0] * a[7]) / det, (a[0] * a[4] - a[1] * a[3]) / det};
    memcpy(out, r, sizeof r);
    return 0;
}

void align_mat3_normalise(double h[9]) {
    const double s = h[8];
    for (int i = 0; i < 9; ++i) h[i] /= s;
}

void align_apply(const double h[9], double x, double y, double *u, double *v) {
    const double w = h[6] * x + h[7] * y + h[8];
    *u = (h[0] * x + h[1] * y + h[2]) / w;
    *v = (h[3] * x + h[4] * y + h[5]) / w;
}

void align_to_level(const double h0[9], int k, double out[9]) {
    const double s = ldexp(1.0, k);
    const double sm[9] = {s, 0, 0, 0, s, 0, 0, 0, 1}, si[9] = {1 / s, 0, 0, 0, 1 / s, 0, 0, 0, 1};
    double t[9];
    align_mat3_mul(h0, sm, t);
    align_mat3_mul(si, t, out);
    align_mat3_normalise(out);
}

void align_from_level(const double hk[9], int k, double out[9]) {
    const double s = ldexp(1.0, k);
    const double sm[9] = {s, 0, 0, 0, s, 0, 0, 0, 1}, si[9] = {1 / s, 0, 0, 0, 1 / s, 0, 0, 0, 1};
    double t[9];
    align_mat3_mul(hk, si, t);
    align_mat3_mul(sm, t, out);
    align_mat3_normalise(out);
}

void align_increment(const double *p, int model, double cx, double cy, double s, double out[9]) {
    double wn[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
    if (model == ALIGN_MODEL_TRANSLATION) {
        wn[2] = p[0];
        wn[5] = p[1];
    } else if (model == ALIGN_MODEL_SIMILARITY) {
        wn[0] = wn[4] = 1 + p[0];
        wn[1] = -p[1];
        wn[3] = p[1];
        wn[2] = p[2];
        wn[5] = p[3];
    } else {
        wn[0] = 1 + p[0];
        wn[3] = p[1];
        wn[1] = p[2];
        wn[4] = 1 + p[3];
        wn[2] = p[4];
        wn[5] = p[5];
        wn[6] = p[6];
        wn[7] = p[7];
    }
    /* N maps pixels to normalised coordinates; the pixel increment is N^-1 Wn N. */
    const double n[9] = {1 / s, 0, -cx / s, 0, 1 / s, -cy / s, 0, 0, 1};
    const double ni[9] = {s, 0, cx, 0, s, cy, 0, 0, 1};
    double t[9];
    align_mat3_mul(wn, n, t);
    align_mat3_mul(ni, t, out);
    align_mat3_normalise(out);
}

int align_solve(double *a, double *b, int n, double *x) {
    for (int c = 0; c < n; ++c) {
        int piv = c;
        for (int r = c + 1; r < n; ++r)
            if (fabs(a[r * n + c]) > fabs(a[piv * n + c])) piv = r;
        if (!(fabs(a[piv * n + c]) > 1e-300)) return -1;
        if (piv != c) {
            for (int k = 0; k < n; ++k) {
                const double t = a[c * n + k];
                a[c * n + k] = a[piv * n + k];
                a[piv * n + k] = t;
            }
            const double t = b[c];
            b[c] = b[piv];
            b[piv] = t;
        }
        for (int r = c + 1; r < n; ++r) {
            const double f = a[r * n + c] / a[c * n + c];
            for (int k = c; k < n; ++k) a[r * n + k] -= f * a[c * n + k];
            b[r] -= f * b[c];
        }
    }
    for (int r = n - 1; r >= 0; --r) {
        double acc = b[r];
        for (int k = r + 1; k < n; ++k) acc -= a[r * n + k] * x[k];
        x[r] = acc / a[r * n + r];
    }
    return 0;
}

int align_invert_sym(const double *a, int n, double *out) {
    double m[100], e[10], col[10];
    for (int j = 0; j < n; ++j) {
        memcpy(m, a, sizeof(double) * (size_t)(n * n));
        for (int i = 0; i < n; ++i) e[i] = i == j ? 1.0 : 0.0;
        if (align_solve(m, e, n, col) != 0) return -1;
        for (int i = 0; i < n; ++i) out[i * n + j] = col[i];
    }
    return 0;
}
