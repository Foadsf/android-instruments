#include <cstring>
#include <vector>

#include "instruments/check.hpp"
#include "instruments/yuv_copy.h"

namespace {
constexpr uint32_t W = 6, H = 4;

// A buffer with a given layout; luma/chroma samples are filled with a pattern that identifies them.
struct Img {
    std::vector<uint8_t> mem;
    yuv_image_t im{};
    // kind: 'p' planar (I420), 'n' NV12 (U then V interleaved), 'v' NV21 (V then U); pad = extra row bytes
    Img(char kind, uint32_t pad) : mem(4096, 0xEE) {
        uint8_t *y = mem.data(), *c = mem.data() + 1024;
        im.plane[0] = {y, W + pad, 1};
        if (kind == 'p') {
            im.plane[1] = {c, W / 2 + pad, 1};
            im.plane[2] = {c + 512, W / 2 + pad, 1};
        } else {
            uint8_t *u = kind == 'n' ? c : c + 1, *v = kind == 'n' ? c + 1 : c;
            im.plane[1] = {u, W + pad, 2};
            im.plane[2] = {v, W + pad, 2};
        }
    }
    uint8_t &at(int p, uint32_t x, uint32_t y) {
        const yuv_plane_t &pl = im.plane[p];
        return pl.data[y * pl.row_stride + x * pl.pixel_stride];
    }
    void fill() {
        for (uint32_t y = 0; y < H; ++y)
            for (uint32_t x = 0; x < W; ++x) at(0, x, y) = static_cast<uint8_t>(y * 16 + x);
        for (uint32_t y = 0; y < H / 2; ++y)
            for (uint32_t x = 0; x < W / 2; ++x) {
                at(1, x, y) = static_cast<uint8_t>(0x80 + y * 8 + x);
                at(2, x, y) = static_cast<uint8_t>(0xC0 + y * 8 + x);
            }
    }
    bool same_samples(Img &o) {
        for (uint32_t y = 0; y < H; ++y)
            for (uint32_t x = 0; x < W; ++x)
                if (at(0, x, y) != o.at(0, x, y)) return false;
        for (int p = 1; p < 3; ++p)
            for (uint32_t y = 0; y < H / 2; ++y)
                for (uint32_t x = 0; x < W / 2; ++x)
                    if (at(p, x, y) != o.at(p, x, y)) return false;
        return true;
    }
};

bool copies(char from, uint32_t from_pad, char to, uint32_t to_pad) {
    Img s(from, from_pad), d(to, to_pad);
    s.fill();
    return yuv420_copy(&s.im, &d.im, W, H) == 0 && d.same_samples(s);
}
}  // namespace

INSTRUMENTS_TEST(same_layout_copies) {
    INSTRUMENTS_CHECK(copies('n', 0, 'n', 0));
    INSTRUMENTS_CHECK(copies('p', 0, 'p', 0));
}

INSTRUMENTS_TEST(nv21_to_nv12_swaps_chroma_order) { INSTRUMENTS_CHECK(copies('v', 0, 'n', 0)); }

INSTRUMENTS_TEST(semi_planar_to_planar_and_back) {
    INSTRUMENTS_CHECK(copies('n', 0, 'p', 0));
    INSTRUMENTS_CHECK(copies('p', 0, 'v', 0));
}

INSTRUMENTS_TEST(padded_rows_both_sides) {
    INSTRUMENTS_CHECK(copies('n', 10, 'n', 3));
    INSTRUMENTS_CHECK(copies('v', 2, 'p', 7));
}

INSTRUMENTS_TEST(padding_bytes_of_destination_are_not_touched) {
    Img s('n', 0), d('n', 4);
    s.fill();
    INSTRUMENTS_CHECK(yuv420_copy(&s.im, &d.im, W, H) == 0);
    INSTRUMENTS_CHECK(d.mem[W] == 0xEE && d.mem[W + 3] == 0xEE);  // row 0 padding of Y
}

// A packed NV21 frame (HAL1 preview callback): Y rows of W bytes, then V,U pairs.
INSTRUMENTS_TEST(packed_nv21_is_described_and_copies) {
    std::vector<uint8_t> nv21(W * H * 3 / 2);
    for (size_t i = 0; i < nv21.size(); ++i) nv21[i] = static_cast<uint8_t>(i);
    yuv_image_t s{};
    INSTRUMENTS_CHECK(yuv_describe_nv21(nv21.data(), W, H, &s) == 0);
    INSTRUMENTS_CHECK(s.plane[0].data == nv21.data() && s.plane[0].row_stride == W);
    INSTRUMENTS_CHECK(s.plane[2].data == nv21.data() + W * H && s.plane[1].data == nv21.data() + W * H + 1);
    INSTRUMENTS_CHECK(s.plane[1].pixel_stride == 2 && s.plane[2].row_stride == W);
    Img d('p', 0);
    INSTRUMENTS_CHECK(yuv420_copy(&s, &d.im, W, H) == 0);
    INSTRUMENTS_CHECK(d.at(0, 5, 3) == nv21[3 * W + 5]);
    INSTRUMENTS_CHECK(d.at(2, 1, 1) == nv21[W * H + W + 2] && d.at(1, 1, 1) == nv21[W * H + W + 3]);
}

INSTRUMENTS_TEST(packed_nv21_refuses_bad_sizes) {
    uint8_t buf[64];
    yuv_image_t s{};
    INSTRUMENTS_CHECK(yuv_describe_nv21(buf, W - 1, H, &s) == -1);
    INSTRUMENTS_CHECK(yuv_describe_nv21(buf, W, 0, &s) == -1);
    INSTRUMENTS_CHECK(yuv_describe_nv21(nullptr, W, H, &s) == -1);
}

INSTRUMENTS_TEST(bad_arguments_are_refused) {
    Img s('n', 0), d('n', 0);
    INSTRUMENTS_CHECK(yuv420_copy(&s.im, &d.im, W - 1, H) == -1);
    INSTRUMENTS_CHECK(yuv420_copy(&s.im, &d.im, W, 0) == -1);
    d.im.plane[0].row_stride = W - 1;
    INSTRUMENTS_CHECK(yuv420_copy(&s.im, &d.im, W, H) == -1);
    d.im.plane[0].row_stride = W;
    d.im.plane[2].data = nullptr;
    INSTRUMENTS_CHECK(yuv420_copy(&s.im, &d.im, W, H) == -1);
    d.im.plane[2].data = d.mem.data() + 1025;
    d.im.plane[1].pixel_stride = 0;
    INSTRUMENTS_CHECK(yuv420_copy(&s.im, &d.im, W, H) == -1);
}
