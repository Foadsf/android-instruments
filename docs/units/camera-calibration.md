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

- **Setup:** the target stays taped flat on the wall, freshly printed after the Epson's nozzle check and head cleaning (`tpdprint print tools/calib/target_a4_v2_landscape.pdf`); Foad re-measures it with the ruler. Foad moves the phone through about 15 poses (distances 20 to 45 cm, tilts up to about 25° each way, a few at 90° roll), resting it on something at each pose.
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
| corners per usable view, camera 0 at about 30 cm | ≥ 60 % of the visible corners | a clean print; the streaked v2 print gave 22 % |
| held-out reprojection RMS | camera 0 ≤ 0.5 px, camera 2 ≤ 0.8 px | sub-pixel corners; camera 2 is softer at this range (seen in run `222032-95ad`) |
| two halves of the views agree | fx within 0.5 %, cx and cy within 3 px | stability of the fit |
| known 100 mm displacement | computed change 100 ± 1.5 mm, on each camera | Foad's ruler (±0.5 mm), plus pose noise |
| straightness after undistortion | max corner deviation from its row or column line ≤ 0.3 px | the distortion model removes the bending |
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

## Not in this unit

- Focus-dependent calibration: a table over focus distances for focus stacking (Stage 3.6).
- Rolling-shutter and time-sync calibration between the IMU and camera timestamps (`motion_prior`).
- Distortion-corrected `warp`.
- Anything on camera 2 that needs focus control (bridge milestone 4).

## Device evidence

None yet. Exploratory first look (run `222032-95ad`, not evidence): accelerometer tilt 12.9° and roll 1.2°; board tilt about 11° on both cameras; distances 274 mm and 250 mm with nominal focal lengths; sheet level to 0.2°.
