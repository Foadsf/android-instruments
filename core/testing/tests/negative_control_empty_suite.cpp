// Negative control: registered WILL_FAIL. A test binary with no cases must fail, so a unit
// whose tests were accidentally compiled out cannot report green.
#include "instruments/check.hpp"
