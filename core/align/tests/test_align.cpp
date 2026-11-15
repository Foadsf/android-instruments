// align unit tests against the analytic synthetic oracle (docs/units/align.md thresholds).
#include <cstdio>
#include <vector>

#include "instruments/check.hpp"
#include "synth_texture.hpp"

namespace {

void report(const char* name, const synth::Score& s) {
    std::fprintf(stderr, "{\"case\": \"%s\", \"rms_x\": %.5f, \"rms_y\": %.5f, \"max\": %.5f, \"mean_se\": %.5f, \"failures\": %d}\n",
                 name, s.rms_x, s.rms_y, s.max_err, s.mean_se, s.failures);
}

// Aligns one rendered pair and returns the control-point errors' maximum (or 1e9 on a refusal).
double one_pair(const synth::Texture& tex, const double truth[9], double sigma, align_result_t* res_out = nullptr) {
    double id[9];
    synth::identity(id);
    const auto r = synth::quantise(synth::render(tex, 512, 512, id), 1.0, 0.0, sigma, 11);
    const auto m = synth::quantise(synth::render(tex, 512, 512, truth), 1.0, 0.0, sigma, 12);
    align_result_t res{};
    const int rc = align_luma(r.data(), 512, m.data(), 512, 512, 512, nullptr, &res);
    if (rc != ALIGN_OK) {
        std::fprintf(stderr, "{\"refused\": %d, \"overlap\": %.3f, \"rms\": %.3f, \"se0\": %.4f, \"disp0\": [%.3f, %.3f]}\n", rc,
                     res.overlap, res.rms, res.cp_se[0][0], res.cp_disp[0][0], res.cp_disp[0][1]);
        return 1e9;
    }
    if (res_out) *res_out = res;
    std::vector<double> ex, ey;
    synth::cp_errors(res.h, truth, 512, 512, ex, ey);
    return std::fmax(synth::max_abs(ex), synth::max_abs(ey));
}

}  // namespace

INSTRUMENTS_TEST(accuracy_noise_2_and_standard_error) {
    const auto s = synth::score(synth::standard_pairs(), 2.0);
    report("noise 2", s);
    INSTRUMENTS_CHECK(s.failures == 0);
    INSTRUMENTS_CHECK(s.rms_x <= 0.01 && s.rms_y <= 0.01);
    INSTRUMENTS_CHECK(s.max_err <= 0.03);
    // The reported standard error must be a usable confidence: actual RMS within a factor of 2.
    const double actual = std::fmax(s.rms_x, s.rms_y);
    INSTRUMENTS_CHECK(actual <= 2.0 * s.mean_se && actual >= 0.5 * s.mean_se);
}

INSTRUMENTS_TEST(accuracy_noise_8) {
    const auto s = synth::score(synth::standard_pairs(), 8.0);
    report("noise 8", s);
    INSTRUMENTS_CHECK(s.failures == 0);
    INSTRUMENTS_CHECK(s.rms_x <= 0.03 && s.rms_y <= 0.03);
}

INSTRUMENTS_TEST(gain_and_offset_do_not_bias) {
    const std::vector<synth::Pair> ten(synth::standard_pairs().begin(), synth::standard_pairs().begin() + 10);
    const auto s = synth::score(ten, 2.0, 1.04, 5.0);
    report("gain 1.04 offset 5", s);
    INSTRUMENTS_CHECK(s.failures == 0);
    INSTRUMENTS_CHECK(s.rms_x <= 0.01 && s.rms_y <= 0.01);
}

INSTRUMENTS_TEST(capture_range_64_px_and_10_percent_scale) {
    const synth::Texture tex = synth::make_texture(2001);
    const double cases[][4] = {{64, 0, 0, 1.0}, {0, -64, 0, 1.0}, {-45, 45, 0.3, 1.0}, {10, -5, 0, 1.10},
                               {-8, 12, -0.3, 0.90}};
    for (const auto& c : cases) {
        double truth[9];
        synth::handheld(c[0], c[1], c[2], c[3], 0, 0, 512, 512, truth);
        const double e = one_pair(tex, truth, 2.0);
        std::fprintf(stderr, "{\"case\": \"range %g,%g roll %g scale %g\", \"max\": %.5f}\n", c[0], c[1], c[2], c[3], e);
        INSTRUMENTS_CHECK(e <= 0.03);
    }
}

INSTRUMENTS_TEST(sign_convention_content_moves_right) {
    const synth::Texture tex = synth::make_texture(2002);
    double truth[9];
    synth::handheld(0.3, 0, 0, 1.0, 0, 0, 512, 512, truth);
    align_result_t res{};
    one_pair(tex, truth, 0.0, &res);
    INSTRUMENTS_CHECK_NEAR(res.cp_disp[0][0], 0.3, 0.01);
    INSTRUMENTS_CHECK_NEAR(res.cp_disp[0][1], 0.0, 0.01);
}

INSTRUMENTS_TEST(flat_scene_is_refused) {
    std::vector<float> flat(512 * 512, 128.0f);
    const auto r = synth::quantise(flat, 1.0, 0.0, 2.0, 1), m = synth::quantise(flat, 1.0, 0.0, 2.0, 2);
    align_result_t res{};
    INSTRUMENTS_CHECK(align_luma(r.data(), 512, m.data(), 512, 512, 512, nullptr, &res) == ALIGN_EUNTEXTURED);
}

INSTRUMENTS_TEST(small_overlap_is_refused) {
    const synth::Texture tex = synth::make_texture(2003);
    double truth[9], id[9];
    synth::identity(id);
    synth::handheld(300, 0, 0, 1.0, 0, 0, 512, 512, truth);
    const auto r = synth::quantise(synth::render(tex, 512, 512, id), 1.0, 0.0, 2.0, 3);
    const auto m = synth::quantise(synth::render(tex, 512, 512, truth), 1.0, 0.0, 2.0, 4);
    align_options_t o{truth, 0};
    align_result_t res{};
    INSTRUMENTS_CHECK(align_luma(r.data(), 512, m.data(), 512, 512, 512, &o, &res) == ALIGN_EOVERLAP);
}

INSTRUMENTS_TEST(invalid_input_is_rejected) {
    std::vector<uint8_t> a(64 * 64, 100), b(64 * 64, 100);
    align_result_t res{};
    INSTRUMENTS_CHECK(align_luma(nullptr, 64, b.data(), 64, 64, 64, nullptr, &res) == ALIGN_EINVAL);
    INSTRUMENTS_CHECK(align_luma(a.data(), 64, b.data(), 64, 63, 64, nullptr, &res) == ALIGN_EINVAL);
    INSTRUMENTS_CHECK(align_luma(a.data(), 32, b.data(), 64, 64, 64, nullptr, &res) == ALIGN_EINVAL);
    INSTRUMENTS_CHECK(align_luma(a.data(), 64, b.data(), 64, 64, 64, nullptr, nullptr) == ALIGN_EINVAL);
}
