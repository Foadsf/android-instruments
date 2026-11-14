#include "instruments/camera_params.h"
#include "instruments/check.hpp"

#include <string>

namespace {
std::string set(const char *params, const char *k, const char *v) {
    char out[256];
    int n = camera_params_set(params, k, v, out, sizeof out);
    return n < 0 ? std::string("<error>") : std::string(out);
}
std::string get(const char *params, const char *k) {
    char out[64];
    return camera_params_get(params, k, out, sizeof out) ? std::string(out) : std::string("<none>");
}
}  // namespace

INSTRUMENTS_TEST(get_finds_whole_keys_only) {
    const char *p = "preview-size=1920x1080;preview-format=yuv420sp;zoom=0";
    INSTRUMENTS_CHECK(get(p, "preview-size") == "1920x1080");
    INSTRUMENTS_CHECK(get(p, "zoom") == "0");
    INSTRUMENTS_CHECK(get(p, "size") == "<none>");      // suffix of a key is not the key
    INSTRUMENTS_CHECK(get(p, "preview") == "<none>");   // prefix of a key is not the key
    INSTRUMENTS_CHECK(get("", "zoom") == "<none>");
}

INSTRUMENTS_TEST(set_replaces_in_place_and_appends_missing) {
    const char *p = "a=1;dual_camera_mode=0;b=2";
    INSTRUMENTS_CHECK(set(p, "dual_camera_mode", "1") == "a=1;dual_camera_mode=1;b=2");
    INSTRUMENTS_CHECK(set(p, "b", "22") == "a=1;dual_camera_mode=0;b=22");
    INSTRUMENTS_CHECK(set(p, "c", "3") == "a=1;dual_camera_mode=0;b=2;c=3");
    INSTRUMENTS_CHECK(set("", "c", "3") == "c=3");
    INSTRUMENTS_CHECK(set("a=1;", "c", "3") == "a=1;c=3");
}

INSTRUMENTS_TEST(set_rejects_separators_and_small_buffers) {
    char out[8];
    INSTRUMENTS_CHECK(camera_params_set("a=1", "k;x", "v", out, sizeof out) == -1);
    INSTRUMENTS_CHECK(camera_params_set("a=1", "k", "v=w", out, sizeof out) == -1);
    INSTRUMENTS_CHECK(camera_params_set("a=1;b=2", "c", "3333", out, sizeof out) == -1);
}
