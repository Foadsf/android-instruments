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

## Amendment: hand-held capture (2026-11-15, before run 2)

Foad cannot hold the phone still and has to hold it in his hand, so the capture must work with tremor and involuntary movement. The still-pose series (wait for stillness, then a 4-frame burst per camera) cannot: run `124500-55c8` never saw a still phone. The capture changes; the thresholds do not.

- **Capture (run mode `sweep`, `SweepMode.kt`):**
  - One camera at a time (camera 0, then camera 2), each streaming to the phone screen for aiming. Foad moves the phone slowly around the screen target, holding it with both hands.
  - **Frame gate (`core/FrameGate.kt`):** a frame is kept only if the gyroscope stayed below the camera's limit over the whole time the sensor saw it. The limit is 0.04 rad/s for camera 0 and 0.02 rad/s for camera 2 (see the evidence and the mechanics run below; the first draft had 0.02 for both). That window runs from the frame's sensor timestamp minus 5 ms to plus the exposure, the rolling-shutter skew and 5 ms (both from the capture result).
  - Camera 2's bridge reports neither exposure nor skew, and stamps the frame at delivery, so its window is the 150 ms before the stamp (mechanics run below).
  - A window with fewer than 4 gyroscope samples is refused. The gyroscope runs at `SENSOR_DELAY_FASTEST`, which needs the `HIGH_SAMPLING_RATE_SENSORS` permission.
  - Kept frames are at least 0.6 s apart, 30 per camera, within 300 s per camera. A short beep marks each kept frame; a long beep marks a camera's start and end.
  - **Camera 0's exposure** is capped at 8 ms: if AE chose longer, manual exposure with the ISO raised to keep exposure × ISO. This roughly halves the motion blur at the gate (AE chose 20 ms on the screen, run `131410-901d`) and covers translation, which the gyroscope cannot see. What was set is recorded.
  - **Each kept frame is one view.** There is no burst averaging: frames of a moving phone cannot be averaged without registering them, and registration would move the corners.
  - **Recorded per frame:** the luma plane, timestamp, exposure, ISO, skew, focus, the gate window, the gyroscope maximum and mean, and the accelerometer mean (±50 ms).
  - **Recorded per camera:** rejections by reason, every candidate frame's gyroscope maximum (Foad's tremor), the exposure cap, and the arrival lag. The raw IMU stream goes to `imu.csv`.
  - **Command:** `run_live.py --cameras 0,2 --sweep 30 --gate 0:0.04,2:0.02 --max-exposure-us 8000 --focus 2.5`.
- **Distances:** camera 0 at 35 to 50 cm (focus 2.5 D; depth of field about 35 to 47 cm), camera 2 at 45 to 65 cm (whole board in view, beyond its near limit of about 40 cm). Tilts up to about 25° each way, and a few frames with the phone on its side.
- **Host:**
  - A sweep series uses the same layout as the still series, one "pose" per kept frame with one camera each, so `calibrate.py` reads it unchanged.
  - **Near-duplicates are dropped:** a kept frame whose shared corners all lie within 30 px of an earlier kept view's adds nothing new, and would flatter the held-out and halves checks. The largest shift is used, not the median: a 20° turn about the board centre moves the median corner less than 30 px but the board's edge by 50 px (seen in the test).
- **Clock check (judged):** the gate compares frame and gyroscope timestamps. All three cameras report timestamp source REALTIME (`dumpsys media.camera`, 2026-11-15), but camera 2 passes through the bridge. Each camera's median arrival lag (arrival time minus sensor timestamp) must therefore lie between 0 and 1000 ms, or the gate is unproven and the run fails.
- **What hand-held capture cannot measure:**
  - **The pair** (`stereoCalibrate`) needs both cameras at one instant, and the bridge gives one stream at a time.
  - **The known 100 mm displacement** needs two still poses.
  - **The NCC ratio** needs one scene seen from one place by both cameras.
  - All three are recorded as "not captured", not judged. The focal length therefore has no outside check in a hand-held run. `imu.csv` is kept so that a gyroscope-against-vision rotation check can be added (`motion_prior`).
- **Synthetic evidence** (`render_moving`: per-row poses for the rolling shutter and the exposure averaged over instants for blur; the rotation is at 0.3 to 1 × the gate in a random direction, about a pivot up to 400 mm away, so the camera also translates; 20 random hand-held views per run):

| Camera, exposure, readout | Gate (rad/s) | Seeds | Focal | Centre (px) | k1 | Held-out (px) | Straightness (px) |
|---|---|---|---|---|---|---|---|
| 0, 20 ms, 25 ms | 0.02 | 3 | ≤ 0.08 % | ≤ 0.56 | ≤ 0.0021 | ≤ 0.08 | ≤ 0.043 |
| 0, 8 ms, 25 ms | 0.02 | 1 | 0.04 % | 0.08 | 0.0022 | 0.10 | 0.048 |
| 0, 8 ms, 32 ms (as run) | 0.04 | 2 | ≤ 0.11 % | ≤ 0.57 | ≤ 0.0019 | ≤ 0.09 | ≤ 0.047 |
| 0, 8 ms, 32 ms (as run) | 0.06 | 2 | ≤ 0.17 % | ≤ 0.98 | ≤ 0.0025 | ≤ 0.11 | ≤ 0.045 |
| 2, 20 ms, 33 ms | 0.04 | 2 | ≤ 0.33 % (fail) | ≤ 6.25 (fail) | ≤ 0.0165 (fail) | ≤ 0.07 | ≤ 0.032 |
| 2, 40 ms, 33 ms | 0.04 | 1 | 0.08 % | 1.52 | 0.0022 | 0.09 | 0.030 |
| 2, 33 to 40 ms, 25 to 33 ms | 0.02 | 3 | ≤ 0.03 % | ≤ 1.17 | ≤ 0.0072 | ≤ 0.08 | ≤ 0.032 |
| 0, 20 ms, 25 ms | 0.05 | 1 | 0.44 % (fail) | 1.86 | 0.0045 | 0.08 | 0.226 (fail) |
| 2, 33 ms, 25 ms | 0.05 | 1 | 0.11 % | 3.34 (fail) | 0.0059 | 0.07 | 0.026 |
| 2, 40 ms, 33 ms (negative control) | 0.2 | 1 | 0.02 % | 6.24 (fail) | 0.035 (fail) | 0.95 (fail) | 0.268 (fail) |

- **Tests:**
  - `HandHeld` in `test_calibrate.py`: camera 2 at 0.02 rad/s and camera 0 at 0.04 rad/s (8 ms, 32 ms) meet every synthetic threshold, and free-hand motion (0.2 rad/s) fails straightness;
  - **Why the limits differ:** camera 0 passes at 0.04 and at 0.06 rad/s with its 8 ms exposure. Camera 2 fails at 0.04 in two of three seeds: its focal length is nearly twice camera 0's, so the same turn smears and shears its image twice as far. Which of blur and rolling shutter matters more is not separated: the passing camera 2 seed had the longer exposure, so seed-to-seed variation is at least as large as the exposure effect. Camera 0 keeps a margin at 0.04 rather than 0.06;
  - `FrameGateTest`: a jerk inside the readout rejects, a jerk outside does not, too few gyroscope samples cannot pass as calm (negative control), and the gap is enforced;
  - the near-duplicate and clock checks in `SeriesCli`.
- **Mechanics run `153949-0113` (5 frames per camera, phone in Foad's hand; he had not been told a run was going, so it includes handling):**
  - 10 of 10 frames were written in the series layout.
  - Camera 0's exposure was capped as designed: AE chose 20 ms at ISO 50; the run used 8 ms at ISO 124. Camera 0 reports a rolling-shutter skew of 32.0 ms.
  - The gyroscope gave 24 to 25 samples per camera 0 window (about 500 Hz).
  - Arrival lag: camera 0 median 155 ms (133 to 187), camera 2 median 21 ms (11 to 35). Both are positive, so the frames and the gyroscope share one clock.
  - **Camera 2's stamp is the delivery time, not the exposure start.** A 21 ms lag is shorter than an exposure plus a readout. The bridge stamps each frame with `CLOCK_BOOTTIME` when HAL1's data callback fires (`bridge_tele.c`), after exposure, readout and the ISP. Camera 2's gate window is therefore the 150 ms before the stamp. That covers the exposure if HAL1's delivery delay is under about 100 ms, which is not measured.
  - **Foad's tremor:**

    | Camera | Median rate (rad/s) | Under 0.02 | Under 0.03 | Under 0.04 | Under 0.05 |
    |---|---|---|---|---|---|
    | 0 | 0.066 | 0.3 % | 2.7 % | 9.7 % | 19 % |
    | 2 | 0.055 | 0.6 % | 4.9 % | 20 % | 31 % |

    The medians are over the calm phases (rate below 0.15 rad/s); the fractions are of all candidates. With 0.3 % of frames under 0.02 rad/s, camera 0 took 138 s for 5 frames: the first gate is unusable for this hand.
  - Every frame is now a candidate (8 slots), where the mechanics run evaluated about 14 per second.

## Amendment: frame timing for camera 2 (2026-11-15, after run 2, before run 3)

Run 2's camera 2 kept only 8 frames in 300 s. Its gate window is the 150 ms before the bridge's delivery stamp, because the HAL1 delay is unknown.

- **Gain:** on run 2's own gyroscope log (`imu.csv`, camera 2's 300 s), the share of windows under 0.02 rad/s is 0.38 % for 150 ms windows, 1.6 % for 70 ms and 3.0 % for 50 ms. Measuring the window would therefore pass about 8 times more frames.
- **Measurement (run mode `timing`, `TimingMode.kt`; host `tools/calib/frame_timing.py`):**
  - Each camera streams for 12 s while the vibration motor gives 60 ms pulses at random gaps of 350 to 800 ms. Foad holds the phone at anything with detail.
  - The app records each frame's timestamp and centre-half sharpness. The raw gyroscope goes to `imu.csv`.
  - The host high-passes the gyroscope (it subtracts a 40 ms moving mean, which removes the hand tremor) and takes the squared norm as vibration energy.
  - It then searches windows [ts + start, ts + end] (start −300 to +100 ms, width 10 to 150 ms) for the one whose mean energy best correlates with each frame's loss of sharpness, normalised by its 31-frame running median.
  - A window with r < 0.4 counts as "could not tell".
- **Control:** camera 0's window is known from its capture result: from the stamp to stamp + exposure + skew (0 to about 40 ms). The method is trusted for camera 2 only if it finds camera 0's window within 6 ms at the start and 10 ms at the end, the margins the synthetic tests hold.
- **First timing run (`161917-a872`): control failed, so the camera 2 result is not used.**
  - **Camera 0:** r = 0.29, below 0.4. It ran under AE at 12 fps, a window of about 62 ms (exposure plus skew), and gave only 155 frames with sharpness swings of ±0.4.
  - **Camera 2:** r = 0.42, window −110 to −5 ms. A pulse-triggered average (scratch, not evidence) shows camera 2's frames softest when stamped 25 to 125 ms after a pulse onset. With a 60 ms pulse, that points to an exposure about −65 to −25 ms from the stamp.
  - **Amendment before the second timing run:** camera 0 is timed with the sweep's 8 ms cap (30 fps), so the control runs as the sweep uses it. Nothing else changes.
- **Second timing run (`162251-1ead`, camera 0 capped at 8 ms):**
  - **Camera 0 (control):** window 14 to 29 ms, r = 0.825.
    - Against the declared expectation (0 to 40 ms, the stamp to stamp + exposure + skew), the start misses by 14 ms.
    - **That expectation was wrong, and it is corrected here after seeing the data.** Sharpness is measured on the centre half of the frame. With a rolling shutter, those rows are exposed from a quarter of the skew after the stamp to three quarters of the skew plus the exposure: 8 to 32 ms for 8 ms and 32 ms.
    - Against that window the control passes (start 6 ms off, end 3 ms off, within 6 and 10). `frame_timing.py` now judges the control against the centre-row window (`centre_window_ms`, tested).
  - **Camera 2:** −150 to −10 ms, r = 0.821, pointed at a dim room. The pulse-triggered average shows camera 2's frames soft from 25 to 200 ms after a pulse onset, where camera 0's response lasts about 75 ms.
    - So camera 2's window here is about as wide as the 150 ms default, and the end of the window is consistent across both runs (−5 and −10 ms).
    - The start differs (−110 and −150 ms), as expected if HAL1's exposure grows in dimmer light. This is a hypothesis: the bridge reports no exposure.
  - **Consequence:** the window must be measured on the calibration scene itself, the bright screen.
    - `run_live.py --sweep ... --measure-bridge` first gives 10 s of pulses on camera 2, then runs the sweep with the measured window.
    - A window that cannot be told, or that does not end before the stamp, is not used, and the sweep keeps 150 ms (`bridge_window_from`, tested).
- **Use:** camera 2's gate window becomes the measured window, widened by 10 ms on each side. Its limit stays at 0.02 rad/s, since the simulation failures at 0.04 do not depend on timing.
- **Tests (`test_frame_timing.py`):**
  - on synthetic gyroscope and frame data, a window before the stamp (−90 to −45 ms) and one after it (0 to 40 ms) are recovered within 6 and 10 ms;
  - blur unrelated to the vibration gives "could not tell" (negative control).

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

**Run 2 (`155558-d0aa`, 2026-11-15, hand-held sweep on the monitor): fail.**
- **Capture:** camera 0 kept 30 frames, camera 2 only 8 in its 300 s limit at 0.02 rad/s. Settings: focus 2.5 D, camera 0 at 8 ms. Clock check: lag 152 ms and 20 ms (pass). Foad found the run too long and tiring.
- **Host:** 3 of camera 0's frames were dropped as near-duplicates. Results: `results/sm-n950f/microscope_series_20261115_155558-d0aa.json` and `camera_calibration_20261115_155558-d0aa.json`.

| Check | Camera 0 (27 views) | Camera 2 (8 views) |
|---|---|---|
| held-out RMS | 0.17 px (pass; run 1 0.78) | 0.54 px (pass) |
| halves: fx | 0.26 % (pass; run 1 1.0 %) | 5.1 % (fail) |
| halves: centre | 4.2 px (fail, limit 3; run 1 13) | 25.6 px (fail) |
| straightness RMS | 0.087 px (pass; run 1 0.26) | 0.25 px (fail) |
| image coverage by corners | 0.60 (recorded) | 0.60 |

- **Camera 0:** fx = 1136.7 px, k1 = 0.151, k2 = −0.391. The centre is the only judged check that fails. Coverage of 0.60 means the image corners were seldom reached, which leaves the centre weakly fixed (a reading, not tested).
- **Camera 2:** 8 views are the minimum, and the halves (4 views each) are not stable. The bottleneck is the strict gate over a 150 ms window. The pair, the displacement and the NCC ratio were recorded as not captured; fx2/fx0 = 1.903.

Not yet captured: the known 100 mm displacement. Exploratory first look (run `222032-95ad`, not evidence): accelerometer tilt 12.9° and roll 1.2°; board tilt about 11° on both cameras; distances 274 mm and 250 mm with nominal focal lengths; sheet level to 0.2°.
