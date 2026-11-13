# Unit: testing harness

- **Stage:** 0
- **Path:** `core/testing`
- **Ported from:** new (the verify-with-negative-control idea is android-hpc's `core/tests`)

## Contract

- **Input:** test cases registered with `INSTRUMENTS_TEST(name)`, using `INSTRUMENTS_CHECK(cond)` and `INSTRUMENTS_CHECK_NEAR(a, b, tol)`.
- **Output:** one JSON line per case on stdout, one JSON line per failed check on stderr; exit 0 only if every check passed and at least one case ran.

## Oracle

Conditions whose truth is known: `1 + 1 == 2`, NaN compared with anything.

## Thresholds

| Check | Threshold |
|---|---|
| `test_check` | exits 0 |
| each negative control | exits non-zero |
| number of negative controls in CI | at least 3 |

## Negative controls

- `negative_control_false_check`: `CHECK(1 == 2)`.
- `negative_control_nan_near`: `CHECK_NEAR(NaN, 0, 1e9)`.
- `negative_control_empty_suite`: a binary with no test cases.

## Device evidence

Host only.
