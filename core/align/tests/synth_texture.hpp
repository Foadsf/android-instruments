// Synthetic oracle for the align unit (docs/units/align.md): an analytic texture, a sum of
// band-limited sinusoids, evaluated in closed form at exactly warped coordinates. Each pixel is
// the box integral over its square, done analytically with the warp's local Jacobian (a cosine
// times sinc factors), so no interpolator touches the truth. Truth is the requested homography.
#pragma once

#include <cmath>
#include <cstdint>
#include <random>
#include <vector>

#include "instruments/align.h"

namespace synth {

constexpr double kPi = 3.14159265358979323846;

struct Wave {
    double fx, fy, phase, amp;
};

struct Texture {
    std::vector<Wave> waves;
};

// Radial frequencies log-uniform in [0.02, 0.35] cycles/px, amplitude ~ 1/f, standard deviation
// about 30 grey levels around 128.
inline Texture make_texture(uint32_t seed, int n = 48) {
    std::mt19937 rng(seed);
    std::uniform_real_distribution<double> u(0.0, 1.0);
    Texture t;
    double power = 0.0;
    for (int i = 0; i < n; ++i) {
        const double f = 0.02 * std::pow(0.35 / 0.02, u(rng)), ang = 2 * kPi * u(rng);
        t.waves.push_back({f * std::cos(ang), f * std::sin(ang), 2 * kPi * u(rng), 1.0 / f});
        power += 0.5 / (f * f);
    }
    const double k = 30.0 / std::sqrt(power);
    for (auto& w : t.waves) w.amp *= k;
    return t;
}

inline double sinc(double x) { return std::fabs(x) < 1e-12 ? 1.0 : std::sin(kPi * x) / (kPi * x); }

// The moving image of size w x h for M(H x) = T(x): pixel y shows T(H^-1 y), box-integrated.
inline std::vector<float> render(const Texture& t, int w, int h, const double hm[9]) {
    double g[9];
    double hc[9];
    for (int i = 0; i < 9; ++i) hc[i] = hm[i];
    // Inverse by adjugate (independent of the unit's own matrix code).
    const double a = hc[0], b = hc[1], c = hc[2], d = hc[3], e = hc[4], f = hc[5], p = hc[6], q = hc[7], r = hc[8];
    const double det = a * (e * r - f * q) - b * (d * r - f * p) + c * (d * q - e * p);
    const double adj[9] = {e * r - f * q, c * q - b * r, b * f - c * e, f * p - d * r, a * r - c * p,
                           c * d - a * f, d * q - e * p, b * p - a * q, a * e - b * d};
    for (int i = 0; i < 9; ++i) g[i] = adj[i] / det;
    std::vector<float> out(size_t(w) * h);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const double ww = g[6] * x + g[7] * y + g[8];
            const double u = (g[0] * x + g[1] * y + g[2]) / ww, v = (g[3] * x + g[4] * y + g[5]) / ww;
            const double uxx = (g[0] - u * g[6]) / ww, uxy = (g[1] - u * g[7]) / ww;
            const double vyx = (g[3] - v * g[6]) / ww, vyy = (g[4] - v * g[7]) / ww;
            double acc = 128.0;
            for (const auto& wv : t.waves) {
                const double kx = wv.fx * uxx + wv.fy * vyx, ky = wv.fx * uxy + wv.fy * vyy;
                acc += wv.amp * std::cos(2 * kPi * (wv.fx * u + wv.fy * v) + wv.phase) * sinc(kx) * sinc(ky);
            }
            out[size_t(y) * w + x] = float(acc);
        }
    }
    return out;
}

inline std::vector<uint8_t> quantise(const std::vector<float>& img, double gain, double offset, double sigma,
                                     uint32_t seed) {
    std::mt19937 rng(seed);
    std::normal_distribution<double> n(0.0, sigma);
    std::vector<uint8_t> out(img.size());
    for (size_t i = 0; i < img.size(); ++i) {
        const double v = std::round(gain * img[i] + offset + (sigma > 0 ? n(rng) : 0.0));
        out[i] = uint8_t(v < 0 ? 0 : (v > 255 ? 255 : v));
    }
    return out;
}

inline void identity(double h[9]) {
    for (int i = 0; i < 9; ++i) h[i] = (i % 4 == 0) ? 1.0 : 0.0;
}

// A hand-held-like homography about the centre: shift (tx, ty), roll (deg), scale, perspective.
inline void handheld(double tx, double ty, double roll_deg, double scale, double p6, double p7, int w, int h,
                     double out[9]) {
    const double cx = (w - 1) / 2.0, cy = (h - 1) / 2.0, th = roll_deg * kPi / 180.0;
    const double cs = scale * std::cos(th), sn = scale * std::sin(th);
    // x' = c + t + R S (x - c), then the perspective about the centre.
    const double m[9] = {cs, -sn, 0, sn, cs, 0, p6, p7, 1};
    double pre[9] = {1, 0, -cx, 0, 1, -cy, 0, 0, 1}, post[9] = {1, 0, cx + tx, 0, 1, cy + ty, 0, 0, 1}, t1[9];
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) t1[3 * i + j] = m[3 * i] * pre[j] + m[3 * i + 1] * pre[3 + j] + m[3 * i + 2] * pre[6 + j];
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) out[3 * i + j] = post[3 * i] * t1[j] + post[3 * i + 1] * t1[3 + j] + post[3 * i + 2] * t1[6 + j];
    for (int i = 0; i < 9; ++i) out[i] /= out[8];
}

// A random homography in the contract's synthetic ranges: shift +-20 px, roll +-0.4 deg, scale
// +-2 %, perspective giving about +-1 px at the corners.
inline void random_handheld(std::mt19937& rng, int w, int h, double out[9]) {
    std::uniform_real_distribution<double> u(-1.0, 1.0);
    const double r = w / 2.0, pk = 1.0 / (r * r);
    handheld(20 * u(rng), 20 * u(rng), 0.4 * u(rng), 1.0 + 0.02 * u(rng), pk * u(rng), pk * u(rng), w, h, out);
}

inline void control_points(int w, int h, double cp[5][2]) {
    const double xs[5] = {(w - 1) / 2.0, (w - 1) / 4.0, 3 * (w - 1) / 4.0, (w - 1) / 4.0, 3 * (w - 1) / 4.0};
    const double ys[5] = {(h - 1) / 2.0, (h - 1) / 4.0, (h - 1) / 4.0, 3 * (h - 1) / 4.0, 3 * (h - 1) / 4.0};
    for (int i = 0; i < 5; ++i) {
        cp[i][0] = xs[i];
        cp[i][1] = ys[i];
    }
}

// Control-point error of an estimate against the truth, per axis, appended to errs.
inline void cp_errors(const double est[9], const double truth[9], int w, int h, std::vector<double>& ex,
                      std::vector<double>& ey) {
    double cp[5][2];
    control_points(w, h, cp);
    for (auto& c : cp) {
        double ue, ve, ut, vt;
        align_apply(est, c[0], c[1], &ue, &ve);
        align_apply(truth, c[0], c[1], &ut, &vt);
        ex.push_back(ue - ut);
        ey.push_back(ve - vt);
    }
}

inline double rms(const std::vector<double>& v) {
    double s = 0;
    for (double x : v) s += x * x;
    return v.empty() ? NAN : std::sqrt(s / double(v.size()));
}

inline double max_abs(const std::vector<double>& v) {
    double m = 0;
    for (double x : v) m = std::fabs(x) > m ? std::fabs(x) : m;
    return m;
}

struct Pair {
    std::vector<float> ref, mov;
    double truth[9];
};

// 50 pairs at 512x512: 5 textures x 10 random hand-held homographies (renders cached per process).
inline const std::vector<Pair>& standard_pairs() {
    static std::vector<Pair> pairs;
    if (!pairs.empty()) return pairs;
    std::mt19937 rng(20261115);
    double id[9];
    identity(id);
    for (int t = 0; t < 5; ++t) {
        const Texture tex = make_texture(1000u + uint32_t(t));
        const std::vector<float> ref = render(tex, 512, 512, id);
        for (int i = 0; i < 10; ++i) {
            Pair p;
            random_handheld(rng, 512, 512, p.truth);
            p.ref = ref;
            p.mov = render(tex, 512, 512, p.truth);
            pairs.push_back(std::move(p));
        }
    }
    return pairs;
}

struct Score {
    double rms_x, rms_y, max_err, mean_se;
    int failures;
};

// Aligns every pair (noise sigma, gain/offset on M) and scores the control-point errors.
inline Score score(const std::vector<Pair>& pairs, double sigma, double gain = 1.0, double offset = 0.0) {
    std::vector<double> ex, ey, se;
    int fails = 0;
    uint32_t seed = 7;
    for (const auto& p : pairs) {
        const auto r = quantise(p.ref, 1.0, 0.0, sigma, seed++);
        const auto m = quantise(p.mov, gain, offset, sigma, seed++);
        align_result_t res{};
        if (align_luma(r.data(), 512, m.data(), 512, 512, 512, nullptr, &res) != ALIGN_OK) {
            ++fails;
            continue;
        }
        cp_errors(res.h, p.truth, 512, 512, ex, ey);
        for (auto& s : res.cp_se) {
            se.push_back(s[0]);
            se.push_back(s[1]);
        }
    }
    double mse = 0;
    for (double s : se) mse += s;
    return {rms(ex), rms(ey), std::fmax(max_abs(ex), max_abs(ey)), se.empty() ? NAN : mse / double(se.size()), fails};
}

}  // namespace synth
