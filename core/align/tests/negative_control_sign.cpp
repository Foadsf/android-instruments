// Negative control (must FAIL): a +0.3 px render asserted to come back as -0.3 px. Catches a
// flipped sign convention in the unit or in the test's oracle.
#include "instruments/check.hpp"
#include "synth_texture.hpp"

INSTRUMENTS_TEST(flipped_sign_is_caught) {
    const synth::Texture tex = synth::make_texture(2002);
    double truth[9], id[9];
    synth::identity(id);
    synth::handheld(0.3, 0, 0, 1.0, 0, 0, 512, 512, truth);
    const auto r = synth::quantise(synth::render(tex, 512, 512, id), 1.0, 0.0, 0.0, 1);
    const auto m = synth::quantise(synth::render(tex, 512, 512, truth), 1.0, 0.0, 0.0, 2);
    align_result_t res{};
    INSTRUMENTS_CHECK(align_luma(r.data(), 512, m.data(), 512, 512, 512, nullptr, &res) == ALIGN_OK);
    INSTRUMENTS_CHECK_NEAR(res.cp_disp[0][0], -0.3, 0.01);
}
