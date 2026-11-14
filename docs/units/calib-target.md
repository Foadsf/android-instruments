# Unit: calib-target (printed A4 calibration target)

- **Stage:** fixture for Stage 7 (camera model, scale) and Stage 8 (fusion), requested by Foad 2026-11-14
- **Path:** `tools/calib/` (`make_target.py` generator, `check_target.py` independent checker, `target_a4_v1.pdf` + `target_a4_v1.json`)
- **Ported from:** "new"; the ChArUco choice follows the plan (Stage 7: metric scale from ChArUco, never from a hard-coded baseline).

## Contract

- **Output:** one A4 portrait vector PDF and a JSON spec giving every feature's position in millimetres on the page (origin at the top-left corner of the paper). Calibration code reads geometry from the spec only.
- **Contents and purpose:**
  - **ChArUco board**, 9x10 squares of 20.0 mm, `DICT_5X5_100` markers of 14.0 mm, outer size 180.0 x 200.0 mm, at (15, 22) mm. Uses: camera intrinsics and distortion, the pose (distance and angle) of each camera to the wall, mm per pixel, wide-to-telephoto scale (closes the pending telephoto check in `microscope-live.md`) and the cross-camera warp.
  - **Slanted-edge square**, 30 mm, rotated 5.0°: MTF by the slanted-edge method, the resolution yardstick for `burst_sr`.
  - **Binary random texture**, 50 mm, fixed seed: alignment and NCC.
  - **Grey patches**, nominal 0 to 100 % black in steps of 20 % (printer tone not calibrated: their order is the only claim): flat areas for noise versus signal (`burst_merge`).
  - **Ruler**, 150.0 mm with 1 mm ticks: Foad's print-scale check.
- **Drawing:** the board is drawn as exact rectangles from OpenCV's own board image at 10 px/mm, where every marker cell is a whole 20 px, so nothing is resampled.

## Oracle

`check_target.py` renders the PDF with PyMuPDF (the generator draws with matplotlib) and finds the board with OpenCV's ChArUco detector. It then checks every inner corner against the spec, the ruler's two ends, the texture's black fraction, the grey order and the edge angle. The printed sheet is checked by Foad with a ruler: the board's 180.0 and 200.0 mm sides, one 20.0 mm square, and the 150.0 mm ruler.

## Thresholds

| Check | Threshold | Result (300 dpi render) |
|---|---|---|
| page | A4, 595.28 x 841.89 pt, one page | pass |
| ChArUco corners detected | 72 of 72 | 72 |
| corner position vs spec | ≤ 0.1 mm max | 0.068 mm (0.034 mm at 600 dpi: rendering resolution, not drawing error) |
| ruler | dark at 0, 75 and 150 mm, white 1.5 mm beyond the end | pass |
| texture black fraction | 0.4 to 0.6 | 0.504 |
| grey patches | strictly darker in order | 255, 204, 153, 102, 51, 0 |
| slanted edge angle | 5.0 ± 0.2° | 5.009° |
| printed sheet (Foad, ruler) | each length within 0.5 mm (0.3 % on 180 mm) | pending |

## Negative control

`test_calib_tools.py`: PDFs drawn with a 19.5 mm square, the board 1 mm off, a 148 mm ruler or a 4° edge, each checked against the true spec, must fail their check; the run-merging that vectorises the bitmaps must cover the bitmap exactly with no overlap.

## Device evidence

None yet: the sheet is to be printed, measured, taped flat on the wall and captured by cameras 0 and 2.
