# Unit: camera_calibration (cameras 0 and 2, from the printed target)

- **Stage:** 7 (`camera_model`, `scale`) pulled forward; it feeds Stage 8 (`cross_camera_register`, `burst_sr`) and the microscope's µm per pixel
- **Path:**
  - host: `tools/calib/calibrate.py`, with tests in `tools/calib/test_calibrate.py`;
  - phone: a capture series in the microscope app (`android/microscope`, run mode `series`);
  - results: `results/<model>/camera_calibration_<date>_<run>.json`.
- **Ported from:** "new", on OpenCV's ChArUco detector, `calibrateCamera` and `stereoCalibrate`. The plan says metric scale comes from ChArUco (Stage 7), never from `LENS_POSE_TRANSLATION` or a hard-coded baseline.

## Why this shape

The first look on 2026-11-14 (run `222032-95ad`, exploratory, scratch script) showed what is missing:
- **Distances disagree:** the nominal focal lengths from the lens metadata put camera 0 at 274 mm from the wall and camera 2 at 250 mm. Two lenses on the same back plate cannot differ by 24 mm in depth, so at least one nominal focal length is wrong. If camera 2's were right, the telephoto magnification would be 1.72; the 2026-11-14 daylight NCC measured 1.87.
- **Tilt disagrees:** the board gives an 11° tilt, the accelerometer 12.9°.
- **Focal length unconstrained:** one nearly head-on view of a flat board cannot fix the focal length.
- **Few corners:** only 14 to 16 of 63 corners were found, partly because of inkjet nozzle streaks in the black squares.

Calibration needs several views at different angles and distances, a clean print, a fixed focus where the camera allows it, and checks that do not come from the fit itself.

## Contract

### Capture (phone, run mode `series`)

- **Setup:** the target is the existing 2026-11-14 print (`tpdprint`, v2 landscape), taped flat on the wall at all four corners. No reprint: the printer does not work properly (amendment below). Foad checked that print with the ruler ("seems OK"). Foad moves the phone through about 15 poses (distances 20 to 45 cm, tilts up to about 25° each way, a few at 90° roll), resting it on something at each pose.
- **Per pose:** the app waits until the gyroscope shows the phone still (rate below 0.01 rad/s for 1 s). It then captures a 4-frame burst from camera 0, closes it, captures a 4-frame burst from camera 2, closes it, and gives a short tone so Foad moves on. With each pose it records:
  - the mean accelerometer and gyroscope readings over the capture, from Android's `SensorManager`, saved raw with timestamps;
  - each camera's reported focus distance, AF mode, exposure and OIS mode.
- **Settings:**
  - OIS off (`--ois off`).
  - Camera 0 at a fixed manual focus, set by a new run extra `focus_diopters` (with AF off and `LENS_FOCUS_DISTANCE` requested). Every pose records the reported focus, and a pose whose reported focus differs from the requested one by more than 0.05 D is discarded.
  - Camera 2 cannot be focused through the bridge (its HAL1 runs continuous AF, and no focus is reported), so its calibration holds only for the focus HAL1 chose. That limit is recorded, not hidden.
- **Command:** `run_live.py --series 15 --focus 3.5 --ois off`, with extras `series`, `still_ms`, `focus_diopters`. The bursts go outside the repository as usual.

### Calibration (host)

- **Input:** the series folder, the target spec (`target_a4_v2_landscape.json`) and Foad's measured sizes. If they differ from the drawing, the measured square size replaces the spec's: the printed size, not the drawn one, is the truth.
- **Per camera** (stream size 1440x1080, which is the full 4:3 field on both cameras):
  - each pose's 4 frames are averaged first (`burst_merge`), to lower noise before corner detection;
  - ChArUco corners are detected; views with fewer than 12 corners are dropped;
  - `calibrateCamera` with the full five-coefficient distortion model gives fx, fy, cx, cy and k1, k2, p1, p2, k3, the per-view poses, and each parameter's standard deviation;
  - the evaluation views (below) are excluded from the fit.
- **Pair:** `stereoCalibrate` on the poses where both cameras see enough corners gives the rotation and translation from camera 0 to camera 2. This is the basis for cross-camera registration at close range, where parallax matters.
- **Derived:**
  - the telephoto-to-wide magnification fx2 / fx0;
  - mm per pixel on the wall at each pose;
  - each pose's distance to the wall and its tilt.
- **IMU (recorded):** each pose's accelerometer gravity, mapped into camera axes, is compared with the board's in-plane "up" direction. One constant rotation between the device and camera axes is fitted, and the residual is reported. That comparison assumes the wall is vertical and the sheet level (measured 0.2° on 2026-11-14), and nothing here controls those, so it is recorded, not judged.
- **Output:** one JSON with all parameters and their uncertainties, per-view residuals, dropped views with the reason, and every check below. Exit codes 0 pass, 1 fail, 2 usage, 3 too few usable views to judge (fewer than 8 per camera).

## Oracle

- **Synthetic, independent renderer:** a NumPy renderer projects the target bitmap through a known camera (focal length, principal point, radial and tangential distortion) by per-pixel inverse mapping, over 15 known poses. It shares no code with OpenCV's projection. Calibrating on those images must recover the known camera.
- **Device, physical:**
  - **Known displacement.** Foad slides the phone straight back 100 mm along the ruler on the table, between two poses. The computed distances to the wall must differ by 100 mm. This tests the focal length against a length measured outside the fit: a 1 % focal-length error is a 1 % distance error.
  - **Straightness.** After undistortion, each row and column of board corners must lie on a straight line. Undistortion only straightens them if the distortion model is right.
  - **Telephoto magnification:** fx2 / fx0 against the independent NCC scale search on the same scene, undistorted. The NCC compares images and knows nothing about the fit.
- **Device, internal (necessary, not sufficient):**
  - reprojection error on held-out views;
  - agreement between calibrations from two disjoint halves of the views.

## Thresholds (declared before the first run)

| Check | Threshold | Source of the number |
|---|---|---|
| synthetic: focal length | within 0.3 % | well-posed 15-view calibration with sub-pixel corners |
| synthetic: principal point | within 2 px | the same |
| synthetic: k1 | within 0.01 | the same |
| synthetic: reported standard deviations | each true error within 3 σ | the uncertainties must be usable |
| print (Foad's ruler) | board 200.0 x 160.0 mm, square 20.0 mm, each within 0.5 mm; else his measurements become the truth | `calib-target.md` |
| corners per usable view, camera 0 at about 30 cm | ≥ 60 % of the visible corners | the streaked print gave 22 % with plain detection, 100 % with the destreaked detection (amendment) |
| held-out reprojection RMS | camera 0 ≤ 0.5 px, camera 2 ≤ 0.8 px | sub-pixel corners; camera 2 is softer at this range (seen in run `222032-95ad`) |
| two halves of the views agree | fx within 0.5 %, cx and cy within 3 px | stability of the fit |
| known 100 mm displacement | computed change 100 ± 1.5 mm, on each camera | Foad's ruler (±0.5 mm), plus pose noise |
| straightness after undistortion | RMS corner deviation from its row or column line ≤ 0.15 px; the max is recorded (amended from max ≤ 0.3 px) | the distortion model removes the bending; streak noise sets the floor (amendment) |
| fx2 / fx0 vs NCC on the same undistorted scene | within 1 % | two independent ways to measure one ratio |
| pair: translation 0 → 2 | recorded; a sanity bound of 5 to 20 mm, and rotation under 3° | the lenses sit side by side on the back plate |
| IMU residual after the fitted rotation | recorded, not judged | depends on the wall and the taping |

## Negative control

- **Synthetic, distortion ignored:** calibrating with k1 = 0.1 rendered in but the distortion fit disabled must fail the straightness check and the focal-length threshold.
- **Synthetic, wrong square size:** a spec claiming 21 mm squares for a 20 mm render must fail the known-displacement check, since every distance scales by 1.05.
- **Device, too few views:** a series with fewer than 8 usable views per camera must exit 3 ("cannot judge"), never pass.
- **Device, overlapping halves:** the halves check given overlapping view sets must refuse, because shared views make the agreement meaningless.
- **Device, moved pose:** a pose captured while the gyroscope showed motion must be dropped and named in the output.

## Amendments made during the host tests (before any device run)

- **Corner detection is re-refined.** On the synthetic renderer, OpenCV 4.13's `CharucoDetector` put every corner +0.5 px off in x and y (mean (0.49, 0.50) px over four poses). One `cornerSubPix` pass brings the mean to 0.00 px and the max to 0.16 px. All detection goes through `calib_core.detect_corners`.
- **k3 is fixed at 0 (model k1, k2, p1, p2).** With all five coefficients free, the synthetic fit gave k3 = 1.56 ± 0.69 against a truth of 0. That pulled k1 off by 0.016 (3.0 σ, so the threshold of 0.01 failed), and left the distortion field 374 px wrong in image corners no board corner reached, while straightness and focal length still passed. Fixing k3 is the usual choice for normal-field phone lenses; if a real lens needs k3, the straightness check will show it. The thresholds are unchanged.
- **Coverage is recorded:** the fraction of an 8 x 6 grid of image cells that hold a detected corner. The capture instructions ask for poses that put the board into every image corner, because the distortion model is only trusted where the data reached.

Found in the phone smoke test (run `224759-33ab`):
- **OIS stayed on.** `run_live.py` always sent `ois=default`, so the stabiliser was never turned off. A series now forces OIS off.
- **Camera 2 echoes focus.** Through the bridge, camera 2 reports the requested focus (3.5 D) and AF off, while the bridge ignores focus (`camera-bridge.md`). So the focus-mismatch rule applies to camera 0 only, and camera 2's reported focus is not evidence of anything.

Host result: `test_calibrate.py` 10/10 (the 10th is the camera-0 focus-mismatch drop), covering:
- recovery of the known camera (focal length, centre, k1, each within 3 σ);
- held-out RMS under 0.5 px;
- straightness;
- the ignored-distortion negative control (fails as required);
- the known displacement, with the 21 mm-square control failing;
- NCC recovery of a 1.864 telephoto ratio within 1 %;
- the IMU rotation fit;
- "cannot judge" with too few views;
- moved poses dropped and named.

## Amendment for the existing print (2026-11-15, before any device run)

The printer cannot make a clean reprint, so the calibration uses the streaked 2026-11-14 sheet.

- **The streaks:** on camera 0 at 29 cm, thin bright vertical lines run through the black areas. They are 1 to 2 px wide (0.25 to 0.5 mm on paper), +20 to +60 grey levels over a black of 57 and a white of 175. They split the marker borders, so plain detection finds 21 of 63 corners.
- **Synthetic model:** `synth_camera.streaked` puts lines like these into the rendered paper, and it reproduces the failure: plain detection loses 20 to 40 % of the corners.
- **Detection (`calib_core.detect_corners`):**
  - markers and corners are found on a 5 x 5 median of the frame;
  - the adaptive threshold window is widened to 43 px, missed markers are re-found, and a corner next to a single marker is accepted;
  - positions are refined with `cornerSubPix` on the original frame. Refining on a median or a morphological opening was no better overall on the synthetic truth: 0.19 to 0.35 px RMS, against 0.20 to 0.26 px on the original.
- **Real frames (sheet not yet flat, so detection data only):**

  | Frames | Camera 0 | Camera 2 |
  |---|---|---|
  | `225402-81cd` | 21 → 63 | 15 → 54 |
  | `222032-95ad` | 16 → 63 | 13 → 54 |

  Camera 2 sees only part of the board.
- **Accuracy on the synthetic streaked renders:**
  - corner error mean below 0.04 px, so no bias;
  - RMS 0.20 to 0.26 px, max under 0.9 px (camera 0 and camera 2 models), against 0.05 to 0.08 px on a clean sheet;
  - the full calibration still meets the synthetic thresholds (all 63 corners in all 15 views; focal length −0.11 %, centre 1.4 px, k1 −0.005, held-out RMS 0.22 px).
- **Straightness is judged by the RMS.** The streak noise put the max corner deviation at 0.52 px with the right lens model, which would fail the old max ≤ 0.3 px. The RMS deviation separates the two cases: 0.087 px with the right model, 0.21 px with distortion ignored (k1 = 0.1). The threshold is RMS ≤ 0.15 px, and the max is recorded.
- **Flatness:** until 2026-11-15 the sheet was taped at the top corners only and was not flat or vertical. Foad then taped the bottom corners too. Frames from before that are not calibration data.
- **Print size:** with the drawn sizes (200 x 160 mm, 20 mm squares) unless Foad's ruler gives other numbers (`--board-mm`). His check of this print found no visible error.

Tests: `test_calibrate.py` gains three streaked-print tests:
- detection recovers the hidden corners without bias, and plain detection loses them (the negative control);
- calibration on streaked views meets the contract;
- ignoring distortion still fails straightness on streaked views.

## Amendment: the target on a monitor (2026-11-15, after run 1, before run 2)

Run 1 showed that the inked sheet is not flat (a warp of up to 1.4 mm). Foad chose a monitor, which is flat and streak-free.

- **Target:** the same 10 x 8 ChArUco board (DICT_5X5_100, marker 0.7 x square), drawn by `tools/calib/screen_target.py`:
  - 70 px squares and 49 px markers (7 cells of 7 px), centred on the 1920 x 1080 LG Full HD monitor (EDID `GSM5B55`). The first version had 120 px squares; Foad asked for a board his 30 cm ruler can span;
  - shown full-screen 1:1 at desktop position (1920, 0);
  - files: `target_screen_lg_fhd.png` and its `.json`.
- **Shown exactly:** `screen_target.py verify` grabs that monitor and requires every pixel to equal the PNG within 2 grey levels. On 2026-11-15 it found 0 pixels off; the same grab shifted by 20 px fails, as it must. It cannot see scaling inside the monitor itself: that is the ruler's job.
- **Scale truth:**
  - **The EDID is wrong.** It says 480 x 270 mm (0.25 mm pitch, a 21.5-inch panel). Foad's ruler on the 120 px board gave about 43.5 x 35 cm over 1200 x 960 px, which is 0.363 mm: a 31.5-inch 1920 x 1080 panel (698.4 mm wide, 0.36375 mm pitch). The nominal pitch is therefore 0.36375 mm, and the 70 px board is nominally 254.6 x 203.7 mm;
  - Foad measures the board's width and height on the screen with the ruler, and `calibrate.py --spec tools/calib/target_screen_lg_fhd.json --board-mm W,H` uses his numbers. If they differ from the nominal size by more than 0.5 mm, that is recorded.
- **Capture changes from run 1:**
  - camera 0 at 30 to 60 cm, and camera 2 only at 40 cm or more (it is blurred nearer);
  - the phone propped at varied angles: turned left and right, tipped up and down, and a few on its side;
  - the 100 mm slide once.
- **Focus for the screen, still to be tested:**
  - On the first full-board screen view (`131410-901d` pose 0, about 53 cm, camera 0 at 3.5 D), the corner noise left after a cubic board-to-image fit was 0.60 px, against 0.31 to 0.36 px on paper views and 0.12 to 0.14 px on an earlier partial screen view (`130950-7e1a`).
  - The 4 frames agree to 0.06 px, so the noise is a fixed pattern in the view, not motion or flicker.
  - Its sign flips between neighbouring corners, which points to corner parity. The whites are not clipped (maximum 219).
  - Hypothesis: defocus (3.5 D focus against a 1.9 D distance) under the camera's non-linear tone curve makes the white squares look larger.
  - Planned test: the same pose at `--focus 2.0`, before any series. The first try (`131946-2602`) saw only a black screen, because the monitor had gone to sleep. `screen_target.py show` now asks Windows to keep the display on while the board is shown.
- **Thresholds:** unchanged. Straightness stays judged by the RMS (≤ 0.15 px), although the screen has no streaks: the threshold was set before this run and stays.
- **Expected risks, checked on the first capture:** moiré between the screen's pixel grid and the camera's pixels (camera 0 sees about 0.25 to 0.5 mm per pixel at 30 to 60 cm, against the 0.364 mm pitch), and refresh banding. The monitor runs at full brightness to avoid PWM flicker.

## Not in this unit

- Focus-dependent calibration: a table over focus distances for focus stacking (Stage 3.6).
- Rolling-shutter and time-sync calibration between the IMU and camera timestamps (`motion_prior`).
- Distortion-corrected `warp`.
- Anything on camera 2 that needs focus control (bridge milestone 4).

## Device evidence

**Run 1 (`124641-dbc4`, 2026-11-15): fail.**
- **Capture:** 15 poses, 14 still. Pose 7 moved and was dropped. Foad set the phone down on the table at each pose. The earlier attempt `124500-55c8` ended at pose 1 ("never still"), because the phone was held in a hand.
- **Results:** `results/sm-n950f/microscope_series_20261115_124641-dbc4.json`, `camera_calibration_20261115_124641-dbc4.json`.

| Check | Camera 0 | Camera 2 |
|---|---|---|
| held-out RMS | 0.78 px (limit 0.5) | 5.0 px (limit 0.8) |
| halves: fx | 1.0 % (limit 0.5 %) | 4.7 % |
| halves: centre | 13 px (limit 3) | 46 px |
| straightness RMS | 0.26 px (limit 0.15) | 1.96 px |
| corner fraction | 1.00 (pass) | 1.00 |

- **Other results:**
  - fx2 / fx0 = 1.861 against NCC 1.843 (1.0 %, limit 1 %): fail by a hair.
  - The pair translation of 11.4 mm and rotation of 0.46° are inside the sanity bounds (recorded).
  - The IMU residual is 0.22° after a fitted 14.8° rotation (recorded).

Diagnosis (scratch scripts on the same views; exploratory, not evidence):
- **Camera 2 is out of focus closer than about 40 cm.**
  - Its Laplacian sharpness is 10 to 13 at 20 to 32 cm, against 17 to 19 at 37 to 42 cm, and the crops are visibly blurred.
  - Its per-view RMS is 0.75 to 1.1 px at 37 to 42 cm and 2 to 6.8 px nearer.
  - The telephoto's near focus limit is beyond the close poses, so camera 2 needs poses at 40 cm or more.
- **Camera 0's residual is a fixed pattern on the paper, not lens-model error.**
  - The residual RMS is 0.44 px at the image centre, the same as further out.
  - Half its variance repeats at the same corner in every view, and the per-corner pattern correlates 0.91 between two halves of the views.
  - `cv2.calibrateCameraRO`, which refines the board points, brings the fit from 0.50 to 0.23 px. That is the synthetic streak floor (0.21 px).
  - Its refined board is a smooth warp of up to 1.4 mm out of plane, so the inked sheet is not flat even when taped at four corners. It also moved the in-plane points by 1.1 mm RMS, which the weak pose geometry (next point) makes unreliable.
- **The poses have little angle diversity.** Every view has a 14.5 to 17° tilt except two (24°, 31°): the phone rested on the table at one attitude, and only the distance changed. That leaves the focal length weakly separated from distance, which matches the halves disagreeing.

Not yet captured: the known 100 mm displacement. Exploratory first look (run `222032-95ad`, not evidence): accelerometer tilt 12.9° and roll 1.2°; board tilt about 11° on both cameras; distances 274 mm and 250 mm with nominal focal lengths; sheet level to 0.2°.
