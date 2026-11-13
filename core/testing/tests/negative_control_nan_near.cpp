// Negative control: registered WILL_FAIL. A NaN result must never pass a tolerance check.
#include "instruments/check.hpp"

INSTRUMENTS_TEST(nan_must_not_be_near_anything) { INSTRUMENTS_CHECK_NEAR(std::nan(""), 0.0, 1e9); }
