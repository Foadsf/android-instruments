# Unit: <name>

- **Stage:** <0..9>
- **Path:** `<folder>`
- **Ported from:** `<repo>/<file>` at `<commit>`, or "new"

## Contract

- **Input:** types, units, ranges, memory layout.
- **Output:** types, units, what an invalid input returns or throws.

## Oracle

What the result is compared with, and why that reference is independent of this code.

## Thresholds (declared before the first run)

| Check | Threshold | Source of the number |
|---|---|---|

## Negative control

The input that must make the test fail, proving the test can fail.

## Device evidence

`results/<model>/<file>`, or "host only".
