// Known answers from the Note8 (SM-N950F, LineageOS 20) halprobe run of 2026-11-14:
// the Samsung HAL counts 2 cameras, answers for IDs 0, 1, 2 (front alias), 3 (telephoto),
// 20 (wide alias) and 50 (telephoto alias).
#include "instruments/camera_idmap.h"
#include "instruments/check.hpp"

namespace {
camera_idmap_t note8() {
    camera_idmap_t m;
    camera_idmap_init(&m, 2, "3");
    return m;
}
}  // namespace

INSTRUMENTS_TEST(note8_telephoto_becomes_framework_id_2) {
    const camera_idmap_t m = note8();
    INSTRUMENTS_CHECK(camera_idmap_count(&m) == 3);
    INSTRUMENTS_CHECK(camera_idmap_to_vendor(&m, 0) == 0);
    INSTRUMENTS_CHECK(camera_idmap_to_vendor(&m, 1) == 1);
    INSTRUMENTS_CHECK(camera_idmap_to_vendor(&m, 2) == 3);
    INSTRUMENTS_CHECK(camera_idmap_to_vendor(&m, 3) == -1);
    INSTRUMENTS_CHECK(camera_idmap_to_vendor(&m, -1) == -1);
}

INSTRUMENTS_TEST(reverse_map_hides_vendor_aliases) {
    const camera_idmap_t m = note8();
    INSTRUMENTS_CHECK(camera_idmap_to_framework(&m, 3) == 2);
    INSTRUMENTS_CHECK(camera_idmap_to_framework(&m, 1) == 1);
    INSTRUMENTS_CHECK(camera_idmap_to_framework(&m, 2) == -1);   // front alias stays hidden
    INSTRUMENTS_CHECK(camera_idmap_to_framework(&m, 50) == -1);  // telephoto alias stays hidden
    INSTRUMENTS_CHECK(camera_idmap_to_framework(&m, 20) == -1);
}

INSTRUMENTS_TEST(parser_skips_counted_duplicate_and_junk_ids) {
    camera_idmap_t m;
    INSTRUMENTS_CHECK(camera_idmap_init(&m, 2, " 1, 3,x,3 ,50,") == 2);
    INSTRUMENTS_CHECK(m.extra_vendor_ids[0] == 3 && m.extra_vendor_ids[1] == 50);
    INSTRUMENTS_CHECK(camera_idmap_init(&m, 2, "") == 0 && camera_idmap_count(&m) == 2);
    INSTRUMENTS_CHECK(camera_idmap_init(&m, 2, nullptr) == 0);
}

INSTRUMENTS_TEST(removing_an_extra_id_shifts_the_rest) {
    camera_idmap_t m;
    camera_idmap_init(&m, 2, "3,50");
    camera_idmap_remove_extra(&m, 0);
    INSTRUMENTS_CHECK(camera_idmap_count(&m) == 3);
    INSTRUMENTS_CHECK(camera_idmap_to_vendor(&m, 2) == 50);
    camera_idmap_remove_extra(&m, 5);  // out of range: no change
    INSTRUMENTS_CHECK(camera_idmap_count(&m) == 3);
}

INSTRUMENTS_TEST(at_most_max_extra_ids_are_kept) {
    camera_idmap_t m;
    INSTRUMENTS_CHECK(camera_idmap_init(&m, 0, "1,2,3,4,5,6,7,8,9,10") == CAMERA_IDMAP_MAX_EXTRA);
}
