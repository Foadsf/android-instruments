// burst_merge_cli <burst_dir> <out_dir> --frames A-B
//
// Merges frame_NN.yuv (packed I420, written by the microscope app) for the inclusive range A..B
// and writes merged_y16.pgm (16-bit PGM, luma in Q8.8), merged.yuv (I420) and merge.json.
// Exit codes: 0 done, 2 usage or invalid input, 3 a file could not be read or written.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>
#include <vector>

#include "instruments/burst_merge.h"

namespace fs = std::filesystem;

namespace {

constexpr int kUsage = 2, kIo = 3;

struct Args {
    fs::path in, out;
    long first = -1, last = -1;
};

bool parse_args(int argc, char** argv, Args& a) {
    if (argc != 5 || std::strcmp(argv[3], "--frames") != 0) return false;
    a.in = argv[1];
    a.out = argv[2];
    char* end = nullptr;
    a.first = std::strtol(argv[4], &end, 10);
    if (end == argv[4] || *end != '-') return false;
    const char* second = end + 1;
    a.last = std::strtol(second, &end, 10);
    return end != second && *end == '\0' && a.first >= 0 && a.last >= a.first;
}

bool read_file(const fs::path& p, std::string& out) {
    std::ifstream f(p, std::ios::binary);
    if (!f) return false;
    out.assign(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
    return true;
}

// Reads an unsigned integer field from the app's burst.json ("key": 123). 0 when absent.
unsigned long json_uint(const std::string& json, const char* key) {
    const std::string k = std::string("\"") + key + "\"";
    size_t at = json.find(k);
    if (at == std::string::npos) return 0;
    at = json.find(':', at + k.size());
    return at == std::string::npos ? 0 : std::strtoul(json.c_str() + at + 1, nullptr, 10);
}

std::string frame_name(long i) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "frame_%02ld.yuv", i);
    return buf;
}

int merge_range(const Args& a, uint32_t w, uint32_t h, burst_merge_t& m) {
    const size_t bytes = size_t(w) * h * 3 / 2;
    std::string data;
    for (long i = a.first; i <= a.last; ++i) {
        if (!read_file(a.in / frame_name(i), data)) {
            std::fprintf(stderr, "cannot read %s\n", frame_name(i).c_str());
            return kIo;
        }
        burst_frame_t f{};
        if (data.size() != bytes ||
            burst_frame_from_i420(reinterpret_cast<const uint8_t*>(data.data()), w, h, &f) != 0 ||
            burst_merge_add(&m, &f) != BURST_MERGE_OK) {
            std::fprintf(stderr, "%s: %zu bytes, expected %zu\n", frame_name(i).c_str(), data.size(),
                         bytes);
            return kUsage;
        }
    }
    return 0;
}

bool write_outputs(const Args& a, const burst_merge_t& m) {
    std::vector<uint16_t> y16(size_t(m.w) * m.h);
    std::vector<uint8_t> i420(size_t(m.w) * m.h * 3 / 2);
    if (burst_merge_finish_y16(&m, y16.data(), m.w) != 0) return false;
    if (burst_merge_finish_i420(&m, i420.data()) != 0) return false;
    std::error_code ec;
    fs::create_directories(a.out, ec);
    std::ofstream pgm(a.out / "merged_y16.pgm", std::ios::binary);
    pgm << "P5\n" << m.w << " " << m.h << "\n65535\n";
    for (uint16_t v : y16) {
        const char be[2] = {char(v >> 8), char(v & 0xFF)};  // PGM 16-bit is big-endian
        pgm.write(be, 2);
    }
    std::ofstream yuv(a.out / "merged.yuv", std::ios::binary);
    yuv.write(reinterpret_cast<const char*>(i420.data()), std::streamsize(i420.size()));
    std::ofstream js(a.out / "merge.json");
    js << "{\"unit\": \"burst_merge\", \"input_dir\": \"" << a.in.filename().string()
       << "\", \"first\": " << a.first << ", \"last\": " << a.last << ", \"n\": " << m.n
       << ", \"width\": " << m.w << ", \"height\": " << m.h << "}\n";
    return bool(pgm) && bool(yuv) && bool(js);
}

}  // namespace

int main(int argc, char** argv) {
    Args a;
    if (!parse_args(argc, argv, a)) {
        std::fprintf(stderr, "usage: burst_merge_cli <burst_dir> <out_dir> --frames A-B\n");
        return kUsage;
    }
    std::string meta;
    if (!read_file(a.in / "burst.json", meta)) {
        std::fprintf(stderr, "cannot read burst.json in %s\n", a.in.string().c_str());
        return kIo;
    }
    const unsigned long w = json_uint(meta, "width"), h = json_uint(meta, "height");
    burst_merge_t m{};
    if (burst_merge_init(&m, uint32_t(w), uint32_t(h)) != BURST_MERGE_OK) {
        std::fprintf(stderr, "invalid size %lux%lu in burst.json\n", w, h);
        return kUsage;
    }
    int rc = merge_range(a, uint32_t(w), uint32_t(h), m);
    if (rc == 0 && !write_outputs(a, m)) rc = kIo;
    burst_merge_free(&m);
    return rc;
}
