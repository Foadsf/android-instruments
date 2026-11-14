// Tests for burst_merge (docs/units/burst-merge.md). Oracles: a double-precision mean computed
// here, and frames with independent noise from this file's own generator.
#include <cmath>
#include <random>
#include <vector>

#include "instruments/check.hpp"
#include "synth_frames.hpp"

using bm_test::Frame;

namespace {

// Random frames with odd strides; returns the double mean of every sample (Y then U then V).
std::vector<Frame> random_frames(uint32_t w, uint32_t h, int n, std::mt19937& rng) {
    std::uniform_int_distribution<int> d(0, 255);
    std::vector<Frame> fs;
    for (int i = 0; i < n; ++i) {
        Frame f(w, h, 5);
        for (auto& b : f.y) b = uint8_t(d(rng));
        for (auto& b : f.u) b = uint8_t(d(rng));
        for (auto& b : f.v) b = uint8_t(d(rng));
        fs.push_back(f);
    }
    return fs;
}

double mean_at(const std::vector<Frame>& fs, int plane, uint32_t x, uint32_t r) {
    double s = 0;
    for (const auto& f : fs) {
        const auto& p = plane == 0 ? f.y : plane == 1 ? f.u : f.v;
        s += p[size_t(r) * (plane == 0 ? f.sy : f.sc) + x];
    }
    return s / double(fs.size());
}

bool merge_all(const std::vector<Frame>& fs, std::vector<uint16_t>& y16, std::vector<uint8_t>& i420) {
    burst_merge_t m{};
    const uint32_t w = fs[0].w, h = fs[0].h;
    // Sized before anything can fail, so a failing merge is a failed check, never a bad index.
    y16.assign(size_t(w + 7) * h, 0);
    i420.assign(size_t(w) * h * 3 / 2, 0);
    if (burst_merge_init(&m, w, h) != BURST_MERGE_OK) return false;
    bool ok = true;
    for (const auto& f : fs) {
        burst_frame_t v = f.view();
        ok = ok && burst_merge_add(&m, &v) == BURST_MERGE_OK;
    }
    ok = ok && burst_merge_finish_y16(&m, y16.data(), w + 7) == BURST_MERGE_OK;
    ok = ok && burst_merge_finish_i420(&m, i420.data()) == BURST_MERGE_OK;
    burst_merge_free(&m);
    return ok;
}

}  // namespace

INSTRUMENTS_TEST(y16_and_i420_equal_the_rounded_double_mean) {
    std::mt19937 rng(7);
    for (int n : {1, 2, 3, 6, 16}) {
        const uint32_t w = 10, h = 6;
        auto fs = random_frames(w, h, n, rng);
        std::vector<uint16_t> y16;
        std::vector<uint8_t> i420;
        INSTRUMENTS_CHECK(merge_all(fs, y16, i420));
        int bad = 0;
        for (uint32_t r = 0; r < h; ++r)
            for (uint32_t x = 0; x < w; ++x) {
                const double m = mean_at(fs, 0, x, r);
                bad += y16[size_t(r) * (w + 7) + x] != uint16_t(std::floor(256.0 * m + 0.5));
                bad += i420[size_t(r) * w + x] != uint8_t(std::floor(m + 0.5));
            }
        const size_t cw = w / 2, ch = h / 2, uo = size_t(w) * h, vo = uo + cw * ch;
        for (uint32_t r = 0; r < ch; ++r)
            for (uint32_t x = 0; x < cw; ++x) {
                bad += i420[uo + r * cw + x] != uint8_t(std::floor(mean_at(fs, 1, x, r) + 0.5));
                bad += i420[vo + r * cw + x] != uint8_t(std::floor(mean_at(fs, 2, x, r) + 0.5));
            }
        INSTRUMENTS_CHECK(bad == 0);
    }
}

INSTRUMENTS_TEST(identical_frames_give_the_frame_back_exactly) {
    std::mt19937 rng(11);
    auto one = random_frames(16, 8, 1, rng);
    std::vector<Frame> fs(9, one[0]);
    std::vector<uint16_t> y16;
    std::vector<uint8_t> i420;
    INSTRUMENTS_CHECK(merge_all(fs, y16, i420));
    std::vector<uint8_t> want(16 * 8 * 3 / 2);
    for (uint32_t r = 0; r < 8; ++r)
        for (uint32_t x = 0; x < 16; ++x) want[r * 16 + x] = one[0].Y(x, r);
    for (uint32_t r = 0; r < 4; ++r)
        for (uint32_t x = 0; x < 8; ++x) {
            want[128 + r * 8 + x] = one[0].U(x, r);
            want[160 + r * 8 + x] = one[0].V(x, r);
        }
    INSTRUMENTS_CHECK(i420 == want);
    INSTRUMENTS_CHECK(y16[0] == uint16_t(one[0].Y(0, 0) * 256));
}

INSTRUMENTS_TEST(gain_is_sqrt_n_for_independent_noise) {
    for (bool textured : {false, true}) {
        std::mt19937 rng(textured ? 21 : 22);
        std::vector<Frame> fs;
        for (int i = 0; i < 32; ++i) fs.push_back(bm_test::noisy(512, 512, textured, 4.0, rng));
        INSTRUMENTS_CHECK_NEAR(bm_test::gain(fs, 4), 2.0, 0.03 * 2.0);
        INSTRUMENTS_CHECK_NEAR(bm_test::gain(fs, 16), 4.0, 0.03 * 4.0);
    }
}

INSTRUMENTS_TEST(invalid_inputs_return_their_error_codes) {
    burst_merge_t m{};
    INSTRUMENTS_CHECK(burst_merge_init(&m, 5, 4) == BURST_MERGE_EINVAL);
    INSTRUMENTS_CHECK(burst_merge_init(&m, 0, 4) == BURST_MERGE_EINVAL);
    INSTRUMENTS_CHECK(burst_merge_init(nullptr, 4, 4) == BURST_MERGE_EINVAL);
    INSTRUMENTS_CHECK(burst_merge_init(&m, 8, 4) == BURST_MERGE_OK);
    std::vector<uint16_t> y16(32);
    std::vector<uint8_t> i420(48);
    INSTRUMENTS_CHECK(burst_merge_finish_y16(&m, y16.data(), 8) == BURST_MERGE_EEMPTY);
    INSTRUMENTS_CHECK(burst_merge_finish_i420(&m, i420.data()) == BURST_MERGE_EEMPTY);
    Frame other(10, 4), good(8, 4);
    burst_frame_t v = other.view();
    INSTRUMENTS_CHECK(burst_merge_add(&m, &v) == BURST_MERGE_EINVAL);  // size mismatch
    v = good.view();
    v.stride[0] = 7;  // shorter than the luma width
    INSTRUMENTS_CHECK(burst_merge_add(&m, &v) == BURST_MERGE_EINVAL);
    v = good.view();
    v.plane[2] = nullptr;
    INSTRUMENTS_CHECK(burst_merge_add(&m, &v) == BURST_MERGE_EINVAL);
    INSTRUMENTS_CHECK(m.n == 0);  // nothing was added by the failed calls
    v = good.view();
    INSTRUMENTS_CHECK(burst_merge_add(&m, &v) == BURST_MERGE_OK);
    INSTRUMENTS_CHECK(burst_merge_finish_y16(&m, y16.data(), 7) == BURST_MERGE_EINVAL);
    m.n = BURST_MERGE_MAX_FRAMES;  // at the cap: one more must be refused
    INSTRUMENTS_CHECK(burst_merge_add(&m, &v) == BURST_MERGE_EFULL);
    burst_merge_free(&m);
    INSTRUMENTS_CHECK(m.sum == nullptr);
}

INSTRUMENTS_TEST(i420_buffer_is_described_as_planes) {
    std::vector<uint8_t> buf(8 * 4 * 3 / 2);
    burst_frame_t f{};
    INSTRUMENTS_CHECK(burst_frame_from_i420(buf.data(), 8, 4, &f) == BURST_MERGE_OK);
    INSTRUMENTS_CHECK(f.plane[1] == buf.data() + 32 && f.plane[2] == buf.data() + 40);
    INSTRUMENTS_CHECK(f.stride[0] == 8 && f.stride[1] == 4 && f.stride[2] == 4);
    INSTRUMENTS_CHECK(burst_frame_from_i420(buf.data(), 7, 4, &f) == BURST_MERGE_EINVAL);
    INSTRUMENTS_CHECK(burst_frame_from_i420(nullptr, 8, 4, &f) == BURST_MERGE_EINVAL);
}
