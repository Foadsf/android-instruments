// Minimal, dependency-free test harness for core units.
//
// Every failed check prints one JSON line to stderr; a test binary exits non-zero if any check
// failed or if it registered no test cases at all (a silently empty binary is a failure, not a
// pass). The harness proves it can fail through negative-control tests registered WILL_FAIL.
#pragma once

#include <cmath>
#include <string>
#include <vector>

namespace instruments::testing {

struct Case {
    const char* name;
    void (*fn)();
};

std::vector<Case>& registry();
void record_failure(const char* file, int line, const std::string& what);
std::string json_escape(const std::string& s);
int run_all();

struct Register {
    Register(const char* name, void (*fn)()) { registry().push_back({name, fn}); }
};

// True when |a - b| <= tol. NaN on either side is never near anything.
inline bool near(double a, double b, double tol) { return std::fabs(a - b) <= tol; }

}  // namespace instruments::testing

#define INSTRUMENTS_CHECK(cond)                                                       \
    do {                                                                              \
        if (!(cond)) ::instruments::testing::record_failure(__FILE__, __LINE__, #cond); \
    } while (0)

#define INSTRUMENTS_CHECK_NEAR(a, b, tol)                                                   \
    do {                                                                                    \
        const double check_a_ = (a), check_b_ = (b);                                        \
        if (!::instruments::testing::near(check_a_, check_b_, (tol)))                       \
            ::instruments::testing::record_failure(                                         \
                __FILE__, __LINE__,                                                         \
                std::string(#a " ~ " #b ": ") + std::to_string(check_a_) + " vs " +         \
                    std::to_string(check_b_));                                              \
    } while (0)

#define INSTRUMENTS_TEST(name)                                          \
    static void name();                                                 \
    static const ::instruments::testing::Register register_##name(#name, name); \
    static void name()
