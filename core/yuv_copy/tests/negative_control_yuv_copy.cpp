// Negative control: registered WILL_FAIL. Claims that after copying NV21 into NV12 the
// destination's U plane holds the source's V samples (a byte-for-byte copy of the interleaved
// block would do that). yuv420_copy must swap the order, so this must fail.
#include <vector>

#include "instruments/check.hpp"
#include "instruments/yuv_copy.h"

INSTRUMENTS_TEST(nv21_into_nv12_must_not_copy_bytes_blindly) {
    std::vector<uint8_t> y(8, 1), s_vu = {0xA0, 0xB0, 0xA1, 0xB1}, d_uv(4, 0);
    yuv_image_t s{{{y.data(), 4, 1}, {s_vu.data() + 1, 4, 2}, {s_vu.data(), 4, 2}}};  // V first
    std::vector<uint8_t> dy(8, 0);
    yuv_image_t d{{{dy.data(), 4, 1}, {d_uv.data(), 4, 2}, {d_uv.data() + 1, 4, 2}}};  // U first
    INSTRUMENTS_CHECK(yuv420_copy(&s, &d, 4, 2) == 0);
    INSTRUMENTS_CHECK(d_uv[0] == 0xA0);  // would be V; correct is U = 0xB0
}
