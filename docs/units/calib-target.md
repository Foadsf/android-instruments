# Unit: calib-target (printed A4 calibration target)

- **Stage:** fixture for Stage 7 (camera model, scale) and Stage 8 (fusion), requested by Foad 2026-11-14
- **Path:** `tools/calib/` (`make_target.py` generator, `check_target.py` independent checker, `target_a4_v1.pdf` + `target_a4_v1.json`)
- **Ported from:** "new"; the ChArUco choice follows the plan (Stage 7: metric scale from ChArUco, never from a hard-coded baseline).

## Revision 2 (2026-11-14): landscape, printed through tpdprint

v1 (portrait) printed from a viewer came out at 0.947 scale: Foad measured about 142 mm for the 150 mm ruler. The Epson XP-3100's IPP Class Driver fits every page to its printable area after the app (about 0.971, measured 2026-10-07), and the viewer's own fit adds more. The established fix is `tpdprint`, which blits at the driver's true pitch with a per-printer, per-orientation calibration measured on paper. That calibration exists for **landscape** only, so v2 is landscape: `target_a4_v2_landscape.pdf`.
- Board: 10x8 squares, 200.0 x 160.0 mm, at (12, 20) mm. 9 rows put ink into the unprintable margin in tpdprint's dry run, because the driver shifts the page by about 2.3 mm; every feature now keeps at least 12 mm from the top and bottom.
- Print: `tpdprint print tools/calib/target_a4_v2_landscape.pdf`. The dry run reports `calibrated: true`, no ink in the unprintable margin, and 360 dpi.
- Checker on v2: 63 of 63 corners, all probes pass. The corner error is 0.013 mm at 300 dpi and 0.007 mm at 600 dpi once corners are re-refined (see the correction below).
- **Correction (2026-11-14, found by the calibration unit's synthetic renderer):** OpenCV 4.13's `CharucoDetector` returns every corner +0.5 px off in x and y; one `cornerSubPix` pass removes it (`calib_core.detect_corners`, used by the checker now). The earlier 0.068 / 0.034 mm (300 / 600 dpi) residual was that offset, not render resolution as first stated: a constant half pixel also halves in mm when the pixels do.
- Paper scale is still unverified until measured: board 200.0 and 160.0 mm, square 20.0 mm, ruler 150.0 mm. Whatever the measurement, calibration uses the measured sizes as truth: the camera model needs the printed size known, not equal to the drawing.

The v1 section below describes the portrait layout (`--layout portrait-v1`).

## Contract (v1)

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
