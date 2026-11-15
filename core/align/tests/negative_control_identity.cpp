// Negative control (must FAIL): a stub "aligner" that always returns the identity, scored by the
// synthetic accuracy test. Test-only, never shipped.
#include <vector>

#include "instruments/check.hpp"
#include "synth_texture.hpp"

INSTRUMENTS_TEST(identity_stub_fails_accuracy) {
    std::vector<double> ex, ey;
    double id[9];
    synth::identity(id);
    const auto& pairs = synth::standard_pairs();
    for (size_t i = 0; i < 10; ++i) synth::cp_errors(id, pairs[i].truth, 512, 512, ex, ey);
    INSTRUMENTS_CHECK(synth::rms(ex) <= 0.01 && synth::rms(ey) <= 0.01);
}
