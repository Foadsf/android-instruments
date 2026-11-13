// Negative control: registered WILL_FAIL. If this binary ever exits 0, CHECK cannot fail and
// every green result in this repository is meaningless.
#include "instruments/check.hpp"

INSTRUMENTS_TEST(a_false_check_must_fail) { INSTRUMENTS_CHECK(1 == 2); }
