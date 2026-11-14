// Negative control: registered WILL_FAIL. Each half holds 16 copies of one noisy frame, so the
// noise is not independent across frames and the merge cannot reduce it: the gain is 1.0, and
// this claim of the sqrt(16) = 4 gain must fail.
#include <random>
#include <vector>

#include "instruments/check.hpp"
#include "synth_frames.hpp"

INSTRUMENTS_TEST(copies_of_one_frame_must_not_show_sqrt_n_gain) {
    std::mt19937 rng(31);
    const bm_test::Frame a = bm_test::noisy(256, 256, true, 4.0, rng);
    const bm_test::Frame b = bm_test::noisy(256, 256, true, 4.0, rng);
    std::vector<bm_test::Frame> fs(16, a);
    fs.insert(fs.end(), 16, b);
    INSTRUMENTS_CHECK_NEAR(bm_test::gain(fs, 16), 4.0, 0.03 * 4.0);
}
