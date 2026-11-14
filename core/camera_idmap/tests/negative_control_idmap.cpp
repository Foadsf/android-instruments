// Negative control: registered WILL_FAIL. Claims the Note8 telephoto maps to framework ID 3;
// it maps to 2, so this must fail. If it passes, the idmap tests cannot detect a wrong mapping.
#include "instruments/camera_idmap.h"
#include "instruments/check.hpp"

INSTRUMENTS_TEST(wrong_mapping_must_fail) {
    camera_idmap_t m;
    camera_idmap_init(&m, 2, "3");
    INSTRUMENTS_CHECK(camera_idmap_to_framework(&m, 3) == 3);
}
