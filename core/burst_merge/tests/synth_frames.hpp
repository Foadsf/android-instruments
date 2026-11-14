// Test fixtures for burst_merge: frames generated here, independently of the code under test.
#pragma once

#include <cmath>
#include <cstdint>
#include <random>
#include <vector>

#include "instruments/burst_merge.h"

namespace bm_test {

// A planar frame owning its bytes, with row strides wider than the planes (odd padding).
struct Frame {
    uint32_t w, h, sy, sc;
    std::vector<uint8_t> y, u, v;
    Frame(uint32_t w_, uint32_t h_, uint32_t pad = 3)
        : w(w_), h(h_), sy(w_ + pad), sc(w_ / 2 + pad), y(size_t(sy) * h_), u(size_t(sc) * (h_ / 2)),
          v(size_t(sc) * (h_ / 2)) {}
    uint8_t& Y(uint32_t x, uint32_t r) { return y[size_t(r) * sy + x]; }
    uint8_t& U(uint32_t x, uint32_t r) { return u[size_t(r) * sc + x]; }
    uint8_t& V(uint32_t x, uint32_t r) { return v[size_t(r) * sc + x]; }
    burst_frame_t view() const { return {{y.data(), u.data(), v.data()}, {sy, sc, sc}, w, h}; }
};

inline uint8_t clip8(double v) {
    return static_cast<uint8_t>(v < 0 ? 0 : v > 255 ? 255 : std::lround(v));
}

// Scene value at a luma pixel: a smooth sinusoidal texture around 128 (+-60), never clipped by
// sigma-4 noise. textured=false gives a flat 128.
inline double scene(uint32_t x, uint32_t y, bool textured) {
    if (!textured) return 128.0;
    return 128.0 + 40.0 * std::sin(0.11 * x) * std::cos(0.07 * y) + 20.0 * std::sin(0.031 * (x + y));
}

// One noisy observation of the scene: independent Gaussian noise of sigma on every sample.
inline Frame noisy(uint32_t w, uint32_t h, bool textured, double sigma, std::mt19937& rng) {
    std::normal_distribution<double> n(0.0, sigma);
    Frame f(w, h);
    for (uint32_t r = 0; r < h; ++r)
        for (uint32_t x = 0; x < w; ++x) f.Y(x, r) = clip8(scene(x, r, textured) + n(rng));
    for (uint32_t r = 0; r < h / 2; ++r)
        for (uint32_t x = 0; x < w / 2; ++x) {
            f.U(x, r) = clip8(128.0 + n(rng));
            f.V(x, r) = clip8(100.0 + n(rng));
        }
    return f;
}

// Merges frames [first, first+count) and returns the luma mean as doubles (Q8.8 / 256).
inline std::vector<double> merged_luma(const std::vector<Frame>& fs, size_t first, size_t count) {
    burst_merge_t m{};
    std::vector<double> out;
    if (burst_merge_init(&m, fs[0].w, fs[0].h) != BURST_MERGE_OK) return out;
    for (size_t i = first; i < first + count; ++i) {
        burst_frame_t v = fs[i].view();
        burst_merge_add(&m, &v);
    }
    std::vector<uint16_t> y16(size_t(fs[0].w) * fs[0].h);
    if (burst_merge_finish_y16(&m, y16.data(), fs[0].w) == BURST_MERGE_OK)
        for (uint16_t q : y16) out.push_back(q / 256.0);
    burst_merge_free(&m);
    return out;
}

inline std::vector<double> luma(const Frame& f) {
    std::vector<double> out;
    for (uint32_t r = 0; r < f.h; ++r)
        for (uint32_t x = 0; x < f.w; ++x) out.push_back(f.y[size_t(r) * f.sy + x]);
    return out;
}

// Standard deviation of (a - b) with the mean difference removed.
inline double diff_std(const std::vector<double>& a, const std::vector<double>& b) {
    if (a.empty() || a.size() != b.size()) return 0.0;
    double s = 0, ss = 0;
    for (size_t i = 0; i < a.size(); ++i) s += a[i] - b[i];
    const double mean = s / double(a.size());
    for (size_t i = 0; i < a.size(); ++i) ss += (a[i] - b[i] - mean) * (a[i] - b[i] - mean);
    return std::sqrt(ss / double(a.size() - 1));
}

// Noise gain of merging n frames: single-frame difference over merged-half difference, from 2n
// frames (A = 0..n-1, B = n..2n-1, disjoint).
inline double gain(const std::vector<Frame>& fs, size_t n) {
    const double single = diff_std(luma(fs[0]), luma(fs[n]));
    const double merged = diff_std(merged_luma(fs, 0, n), merged_luma(fs, n, n));
    return merged > 0 ? single / merged : 0.0;
}

}  // namespace bm_test
