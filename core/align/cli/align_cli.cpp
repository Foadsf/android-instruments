// align_cli --size WxH <ref> <moving> [--init h11,h12,h13,h21,h22,h23,h31,h32] [--model NAME]
//
// Aligns two raw 8-bit luma or packed I420 files (only the first w*h bytes are read) and prints one
// JSON line (docs/units/align.md). --model limits the warp (translation, similarity, homography;
// default homography). Exit codes: 0 done, 2 usage, 3 file error, 4 refused (untextured or overlap).
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

#include "instruments/align.h"

namespace {

constexpr int kUsage = 2, kIo = 3, kRefused = 4;

struct Args {
    unsigned w = 0, h = 0;
    std::string ref, mov;
    bool has_init = false;
    double init[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
    int model = ALIGN_MODEL_HOMOGRAPHY;
};

bool parse_init(const char* s, double h[9]) {
    char* end = nullptr;
    for (int i = 0; i < 8; ++i) {
        h[i] = std::strtod(s, &end);
        if (end == s || (i < 7 && *end != ',') || (i == 7 && *end != '\0')) return false;
        s = end + 1;
    }
    h[8] = 1.0;
    return true;
}

bool parse_args(int argc, char** argv, Args& a) {
    std::vector<std::string> pos;
    for (int i = 1; i < argc; ++i) {
        const std::string k = argv[i];
        if (k == "--size" && i + 1 < argc) {
            char* end = nullptr;
            const char* s = argv[++i];
            a.w = unsigned(std::strtoul(s, &end, 10));
            if (end == s || *end != 'x') return false;
            const char* s2 = end + 1;
            a.h = unsigned(std::strtoul(s2, &end, 10));
            if (end == s2 || *end != '\0') return false;
        } else if (k == "--init" && i + 1 < argc) {
            if (!parse_init(argv[++i], a.init)) return false;
            a.has_init = true;
        } else if (k == "--model" && i + 1 < argc) {
            const std::string m = argv[++i];
            a.model = m == "translation" ? ALIGN_MODEL_TRANSLATION
                      : m == "similarity" ? ALIGN_MODEL_SIMILARITY
                      : m == "homography" ? ALIGN_MODEL_HOMOGRAPHY : 0;
            if (a.model == 0) return false;
        } else {
            pos.push_back(k);
        }
    }
    if (pos.size() != 2 || a.w < 64 || a.h < 64) return false;
    a.ref = pos[0];
    a.mov = pos[1];
    return true;
}

bool read_luma(const std::string& path, size_t bytes, std::vector<uint8_t>& out) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    out.assign(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
    if (out.size() < bytes) return false;
    out.resize(bytes);
    return true;
}

void print_pairs(const char* key, const double v[ALIGN_CONTROL_POINTS][2]) {
    std::printf(", \"%s\": [", key);
    for (int k = 0; k < ALIGN_CONTROL_POINTS; ++k) std::printf("%s[%.6f, %.6f]", k ? ", " : "", v[k][0], v[k][1]);
    std::printf("]");
}

void print_result(int rc, const align_result_t& r, int model) {
    const char* status = rc == ALIGN_OK ? "ok" : rc == ALIGN_EUNTEXTURED ? "untextured" : rc == ALIGN_EOVERLAP ? "overlap" : "error";
    std::printf("{\"status\": \"%s\", \"model\": %d, \"h\": [", status, model);
    for (int i = 0; i < 9; ++i) std::printf("%s%.12g", i ? ", " : "", r.h[i]);
    std::printf("], \"gain\": %.6f, \"offset\": %.4f, \"rms\": %.4f, \"samples\": %u, \"converged\": %s, \"overlap\": %.4f",
                r.gain, r.offset, r.rms, r.samples, r.converged ? "true" : "false", r.overlap);
    print_pairs("cp", r.cp);
    print_pairs("cp_disp", r.cp_disp);
    print_pairs("cp_se", r.cp_se);
    std::printf("}\n");
}

}  // namespace

int main(int argc, char** argv) {
    Args a;
    if (!parse_args(argc, argv, a)) {
        std::fprintf(stderr, "usage: align_cli --size WxH <ref> <moving> [--init h11,...,h32] [--model translation|similarity|homography]\n");
        return kUsage;
    }
    std::vector<uint8_t> r, m;
    const size_t bytes = size_t(a.w) * a.h;
    if (!read_luma(a.ref, bytes, r) || !read_luma(a.mov, bytes, m)) {
        std::fprintf(stderr, "cannot read %zu bytes from both inputs\n", bytes);
        return kIo;
    }
    align_options_t o{a.has_init ? a.init : nullptr, a.model};
    align_result_t res{};
    const int rc = align_luma(r.data(), a.w, m.data(), a.w, a.w, a.h, &o, &res);
    print_result(rc, res, a.model);
    if (rc == ALIGN_EUNTEXTURED || rc == ALIGN_EOVERLAP) return kRefused;
    return rc == ALIGN_OK ? 0 : kUsage;
}
