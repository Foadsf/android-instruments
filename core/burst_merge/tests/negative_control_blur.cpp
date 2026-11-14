// Negative control: registered WILL_FAIL. A 3x3 box blur applied to the merge output (here, in the
// fixture, never in the library) would fake a noise gain. The identical-frames bit-exact check
// must catch it, so this claim that the blurred output equals the input frame must fail.
#include <random>
#include <vector>

#include "instruments/check.hpp"
#include "synth_frames.hpp"

INSTRUMENTS_TEST(blurred_merge_must_fail_the_bit_exact_check) {
    std::mt19937 rng(41);
    const bm_test::Frame f = bm_test::noisy(32, 32, true, 4.0, rng);
    std::vector<bm_test::Frame> fs(4, f);
    std::vector<double> m = bm_test::merged_luma(fs, 0, 4);
    INSTRUMENTS_CHECK(m.size() == 32 * 32);
    if (m.size() != 32 * 32) return;
    std::vector<double> blurred(m);
    for (int r = 1; r < 31; ++r)
        for (int x = 1; x < 31; ++x) {
            double s = 0;
            for (int dr = -1; dr <= 1; ++dr)
                for (int dx = -1; dx <= 1; ++dx) s += m[size_t(r + dr) * 32 + size_t(x + dx)];
            blurred[size_t(r) * 32 + size_t(x)] = s / 9.0;
        }
    INSTRUMENTS_CHECK(blurred == bm_test::luma(f));
}
