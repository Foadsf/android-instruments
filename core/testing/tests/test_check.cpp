// Positive tests: the harness passes what is true.
#include "instruments/check.hpp"

using instruments::testing::json_escape;
using instruments::testing::near;

INSTRUMENTS_TEST(true_conditions_pass) {
    INSTRUMENTS_CHECK(1 + 1 == 2);
    INSTRUMENTS_CHECK_NEAR(0.1 + 0.2, 0.3, 1e-12);
}

INSTRUMENTS_TEST(near_rejects_nan_and_far_values) {
    INSTRUMENTS_CHECK(!near(std::nan(""), 0.0, 1.0));
    INSTRUMENTS_CHECK(!near(0.0, std::nan(""), 1.0));
    INSTRUMENTS_CHECK(!near(1.0, 1.1, 0.05));
    INSTRUMENTS_CHECK(near(1.0, 1.04, 0.05));
}

INSTRUMENTS_TEST(json_escape_handles_quotes_backslashes_and_controls) {
    INSTRUMENTS_CHECK(json_escape("a\"b") == "a\\\"b");
    INSTRUMENTS_CHECK(json_escape("C:\\x") == "C:\\\\x");
    INSTRUMENTS_CHECK(json_escape("l1\nl2") == "l1\\nl2");
    INSTRUMENTS_CHECK(json_escape(std::string(1, '\x01')) == "\\u0001");
}
