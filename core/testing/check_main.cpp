#include "instruments/check.hpp"

#include <cstdio>

namespace instruments::testing {

namespace {
int failures = 0;
}

std::vector<Case>& registry() {
    static std::vector<Case> cases;
    return cases;
}

std::string json_escape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (const char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof buf, "\\u%04x", static_cast<unsigned>(c));
                    out += buf;
                } else {
                    out += c;
                }
        }
    }
    return out;
}

void record_failure(const char* file, int line, const std::string& what) {
    ++failures;
    std::fprintf(stderr, "{\"event\":\"check.failed\",\"file\":\"%s\",\"line\":%d,\"what\":\"%s\"}\n",
                 json_escape(file).c_str(), line, json_escape(what).c_str());
}

int run_all() {
    if (registry().empty()) {
        std::fprintf(stderr, "{\"event\":\"suite.empty\",\"what\":\"no test cases registered\"}\n");
        return 1;
    }
    for (const Case& c : registry()) {
        const int before = failures;
        c.fn();
        const bool ok = failures == before;
        std::printf("{\"event\":\"case.%s\",\"name\":\"%s\"}\n", ok ? "passed" : "failed",
                    json_escape(c.name).c_str());
    }
    std::printf("{\"event\":\"suite.done\",\"cases\":%zu,\"failed_checks\":%d}\n", registry().size(),
                failures);
    return failures == 0 ? 0 : 1;
}

}  // namespace instruments::testing

int main() { return instruments::testing::run_all(); }
