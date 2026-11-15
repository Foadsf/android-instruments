// Negative control (must FAIL): the same method built with bilinear sampling of M
// (ALIGN_TEST_BILINEAR), held to the bicubic build's accuracy threshold. Its bias shows that the
// choice of bicubic is backed by a measurement.
#include <cstdio>

#include "instruments/check.hpp"
#include "synth_texture.hpp"

INSTRUMENTS_TEST(bilinear_sampling_shows_its_bias) {
    const auto s = synth::score(synth::standard_pairs(), 2.0);
    std::fprintf(stderr, "{\"case\": \"bilinear noise 2\", \"rms_x\": %.5f, \"rms_y\": %.5f, \"max\": %.5f}\n",
                 s.rms_x, s.rms_y, s.max_err);
    INSTRUMENTS_CHECK(s.failures == 0);
    INSTRUMENTS_CHECK(s.rms_x <= 0.01 && s.rms_y <= 0.01);
    INSTRUMENTS_CHECK(s.max_err <= 0.03);
}
