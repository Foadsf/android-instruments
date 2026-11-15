# Unit: microscope_scale (µm per pixel and a scale bar on camera 0)

- **Stage:** 6, first slice (the plan's 3.9 `optics` on the device). This is the first thing in the rebuild that Foad can use as an instrument: point camera 0 at an object, read sizes off a scale bar, and save frames that carry their own µm per pixel.
- **Path:**
  - pure maths in `android/microscope/src/main/java/.../core/Optics.kt` (JVM-tested);
  - the scale bar and the saved scale in the microscope app;
  - the host check in `tools/calib/scale_check.py`.
- **Ported from:** android-microscope `Optics` (the thin-lens relation), one function at a time, with its hand calculation as a test. The calibrated focal length comes from this repository's camera 0 calibration (runs `155558-d0aa` and `163037-f2e7`).

## Why this shape

Stage 6 as planned needs alignment, focus stacking, depth from focus and metrology (Stage 3), which are weeks of work. Scale is useful on its own and needs none of them: it is a measurement of length, the first thing a microscope must get right, and every later unit (heights, stitching, the 3D scanner) inherits it.

Facts it rests on, from `dumpsys media.camera` on the Note8 (2026-11-15):
- camera 0 has f = 4.30 mm (nominal) and a sensor 5.645 mm wide;
- its focus distance is reported as CALIBRATED;
- its closest focus is 10 diopters (10 cm).

At the stream's 1440 px width that is 3.92 µm per sensor pixel. At 10 cm the nominal optics give about 85 µm per pixel on the object (about 30 µm at the sensor's full 4032 px). It is a measuring magnifier, not a high-power microscope, unless a clip-on lens is added (which would need its own calibration).

## Contract

- **Input:**
  - camera 0, continuous autofocus (it works hand-held), OIS off;
  - each frame's `LENS_FOCUS_DISTANCE` (diopters);
  - the calibration constants: fx0 = 1136.5 px at D0 = 2.5 D (the mean of runs 2 and 3, which agree to 0.03 %), the pixel pitch, and the principal point.
- **Model (`Optics.kt`):**
  - thin lens with the focal length fitted to the calibration: 1/f = 1/v0 + D0, with v0 = fx0 × pitch;
  - at focus D, the image distance is v(D) = 1 / (1/f − D) (focus breathing), the focal length in pixels is fx(D) = v(D) / pitch, and the scale on the plane in focus is µm per px = 1000 / (D × fx(D)) × 1000 (D in 1/m);
  - invalid input (D ≤ 0, D ≥ 1/f, or focus not reported) returns no scale, never a guess.
- **Output:**
  - on screen: a scale bar of a round length (0.5, 1, 2 or 5 mm), sized from the current frame's focus, plus the number "µm/px";
  - on Save: a hand-held burst for fusion, not a single frame:
    - 16 consecutive frames (raw I420, OIS off, as `burst-merge.md` uses);
    - the raw gyroscope and accelerometer for the burst (`imu.csv`, 500 Hz, same clock);
    - per frame: focus distance, exposure, skew and the gyroscope maximum over its exposure;
    - `scale.json`: fx(D), µm per px per frame, the calibration run ids, and the model version.
  - The scale bar is drawn from the newest frame. The burst's frames are all kept, with their gyroscope maxima, so the fusion units choose which to use.

## Oracle

Two references, neither computed by `Optics.kt`:

- **Screen board at close range:** the same ChArUco board drawn small on the LG monitor (20 px squares = 7.275 mm at the 0.36375 mm pitch that Foad's ruler confirmed). The board's detected corners give the true mm per pixel on the board plane, from the local scale of the board-to-image homography at the image centre. Each of ≥ 6 hand-held frames at 10 to 30 cm (≥ 3 distances) is compared with `Optics.kt`'s prediction from that frame's reported focus.
- **Ruler (recorded, not judged):** Foad's steel ruler photographed once. The mm ticks spanning the frame, measured by hand on the saved image against the saved scale, are recorded as a sanity check that the app's own pipeline (bar, saved JSON) carries the same number.

### How `scale_check.py` judges (declared 2026-11-15, before the first run)

- **Board scale per frame:**
  - the detected corners are undistorted with camera 0's calibration (run `163037-f2e7`: K and k1, k2, p1, p2);
  - the board's pose comes from the undistorted points (IPPE) with the calibration's K;
  - the board's depth on the ray through the corners' centroid, over fx, is the µm per px of a plane square to the camera at that depth, which is what the model predicts. A wrong fx in K (focus breathing) scales the depth and fx alike, so it does not bias the ratio, and a hand-held tilt does not either.
  - The first draft took the smaller singular value of the homography's Jacobian. The synthetic test showed it 0.7 % low for a board tilted 20° and off-centre, so it was replaced before any run.
  - Without undistortion the scale is 0.9 % off on the synthetic board whose centroid sits about 270 px from the centre (k1 = 0.15). The test requires that bias to exceed 0.5 %, half the median tolerance.
- **Frames judged:** continuous AF reports focused (PASSIVE_FOCUSED or FOCUSED_LOCKED), at least 12 corners are found, and the reported focus gives a scale. The others are recorded with their reason. The run mode waits up to 2 s for focus before each burst.
- **Distances:** the judged frames' focus distances (100 / D cm), sorted, start a new distance wherever the gap is 2 cm or more.
- **Per frame:** every judged frame must be within 2 %.
- **Pipeline check:** the app's saved µm per px must equal the host's own thin-lens computation from the same focus to 0.1 %.
- **Negative controls** run the same tool with `--model no-breathing`, `--model nominal` or `--square-mm 7.63875` (21 px). They need ≥ 6 judged frames but no distance rule, and `no-breathing` uses only the frames nearer than 12 cm. Each must come out "fail".
- **Capture:** the run mode records 3 bursts of 16 frames, 5 s apart: about 25 s of holding at about 10, 15 and 20 cm. The board has 20 px squares, 72.75 x 58.2 mm on the LG monitor, and Foad aims at its centre.

## Thresholds (declared before the first run)

| Check | Threshold | Source of the number |
|---|---|---|
| hand calculation (JVM test) | the android-microscope reference case and the camera 0 case at 10 D reproduce to 0.1 % | arithmetic |
| predicted vs board µm per px, per frame | within 2 % | Depth of field at 10 cm is a few mm, so the plane in focus can sit 1 to 2 % from the reported distance; 2 % separates that from the negative controls (3.4 % and more) |
| predicted vs board, median over frames | within 1 % | the bias, if any, must be smaller than the per-frame spread allows |
| frames judged | ≥ 6 at ≥ 3 distances | otherwise "cannot judge" (exit 3) |
| ruler sanity | recorded | read by hand |

## Negative control

- **Ignoring focus breathing** (fx0 used at every focus): at 10 cm the predicted scale is about 3.4 % off, which must fail the 2 % check on the near frames.
- **Nominal focal length** (4.30 mm and the sensor's nominal pitch, without the calibration): about 2.5 % off at every distance from 10 to 40 cm, which must fail the 1 % median check (and most frames of the 2 % check).
- **Wrong board size** (a spec claiming 21 px squares) must fail every frame by about 5 %.

Correction (2026-11-15, before any device run, found by the hand calculation in `OpticsTest`): the first draft gave the nominal control as 3.5 % at 40 cm and 7 % at 10 cm. The thin lens gives 2.5 % at 40 cm, 2.5 % at 20 cm and 2.6 % at 10 cm. Ignoring breathing gives 3.5 % at 10 cm, 1.1 % at 20 cm and 0.4 % at 30 cm, so that control is judged on the frames nearer than 12 cm only. Hand-calculated scale at 10 D: f = 4.4062 mm, fx = 1175.8 px, 85.05 µm per px.

## Where this leads: fusion (Foad, 2026-11-15)

Sensor fusion is one of the keys: the phone's pose is measured over frames, and the frames are then combined into one image of better quality, resolution and SNR. The pose comes from the images (structure from motion, not only monocular: the rear cameras sit at a fixed pose on the phone's frame) and from the phone's other sensors. Hand-held capture suits this. Tremor moves each frame by a different sub-pixel offset, which is the sampling multi-frame super-resolution needs. The slices after this one, each its own contract:

1. **`align`** (`align.md`, drafted, waiting for review): the shift between hand-held frames, ≤ 0.02 px on the device, with the gyroscope as the starting guess (`motion_prior`).
2. **Hand-held burst merge on camera 0:** `burst_merge` on aligned frames, for SNR, judged by its two-halves oracle against √N.
3. **Hand-held super-resolution on camera 0 (`burst_sr`, 2x):** judged against camera 2's frame of the same scene, a true optical reference about 1.9x finer. This scale unit makes both images metric.
4. **Pose per frame:** 6-DoF from the board, or the scene's features, plus the IMU; then **the multi-camera rig**: camera 0 and camera 2 as one rigid stereo pair (`stereoCalibrate` extrinsics), giving pose and depth from each instant rather than from motion alone.
   - **Open decision:** on the Note8 the rig needs both cameras at the same instant, and the bridge gives one stream at a time. Simultaneous streams are bridge work, together with camera 2's exposure report.
5. Heights (depth from focus), focus stacking and stitching on the fused frames.

## Not in this unit

- Everything in the list above.
- Clip-on lenses.

## Device evidence

### Run 1: `190102-7738` (2026-11-15, hand-held, 20 px screen board): fail

- **Capture:** 3 bursts of 16 frames at about 12, 15.6 and 19.2 cm (board distance). Every frame had continuous AF at PASSIVE_FOCUSED, 63 of 63 corners, exposure 20 ms, and a gyroscope maximum of 0.02 to 0.05 rad/s.
- **Result:** fail.
  - 44 of 48 frames were judged, at 3 distances.
  - The predicted scale is 10 to 19 % larger than the board's: median +15.4 %, maximum +19.0 %.
  - The app's saved µm per px equals the host's thin-lens computation to 4e-8, so the pipeline is right and the error lies in an input.
  - Results: `microscope_scale_20261115_190102-7738.json` and `microscope_scale_check_20261115_190102-7738_calibrated.json`.
- **What fails is the reported focus distance, not the lens model.** The focus at which the model gives the board's scale is the reported focus plus 0.84 D on average (sd 0.08 D over the 44 frames):

  | Reported focus | Frames | Focus that fits the board |
  |---|---|---|
  | 4.37 D (22.9 cm) | 16 | 5.17 ± 0.01 D (19.3 cm) |
  | 5.57 D (18.0 cm) | 16 | 6.38 ± 0.03 D (15.7 cm) |
  | 7.32 D (13.7 cm) | 7 | 8.31 ± 0.09 D (12.0 cm) |
  | 7.77 D (12.9 cm) | 4 | 8.59 ± 0.07 D |

  - The straight-line fit is: fitted focus = 1.033 × reported + 0.65 D, with residuals of 0.07 D.
  - The offset is constant in diopters, not in distance (the distance gaps are 1.7, 2.4 and 3.6 cm). That is the signature of an offset in the lens-position-to-diopter map, not of a different distance reference such as the front of the phone versus the lens.
- **Hypothesis, not tested:** the same offset applies at the calibration's fixed 2.5 D. The lens would then have been focused near 3.3 D (30 cm) while the board sat at 41 to 52 cm. That fits the defocus suspected on the calibration screen views (the camera-calibration amendment "Focus for the screen").
- **Negative controls:** not run. The calibrated model already fails, so a control failing would show nothing.
- **Status:** the scale bar is 10 to 19 % too large at 12 to 20 cm. It must not be used for measurement until a focus correction passes on a new run.

### Amendment: focus offset (2026-11-15, after run 1, before run 2; Foad approved)

- **Model 2 (`thin-lens-breathing-2-focus-offset`):** true focus = reported + δ, with δ = 0.824 D for camera 0.
  - The offset applies to the calibration's fixed focus too: D0 = 2.5 + δ. The lens then has f = 4.3902 mm, and fx at a given reported focus is unchanged; only the object distance moves.
  - δ was fitted on run 1 so that its median error is zero.
  - Fitting δ to the frames only, leaving D0 at 2.5, gives 0.806 D, nearly the same. The joint form is chosen because one lens-position map serves both.
- **Hand calculation:** at a reported 10 D (10.82 D true), fx = 1175.8 px and the scale is 78.58 µm per px; at a reported 5 D it is 149.40 µm per px.
- **Run 1 under model 2 (the data it was fitted on, so not evidence):**
  - median 0.0 %, maximum 4.4 %;
  - bursts 2 and 3 (held steady) are within 1.1 %;
  - burst 1 reaches +4.4 %. There the board drifted from 94.7 to 104.3 µm per px (about 1 cm) within the burst, while the reported focus stayed at 7.32 D for 7 frames. AF does not refocus inside its depth of field (about ±0.7 D at f/1.7 with a 2 px blur circle).
  - Scale from focus is therefore limited to about (focus error) / D per frame while the hand drifts.
- **Run 2 judges model 2 with the thresholds unchanged:** 2 % per frame, 1 % median, ≥ 6 frames at ≥ 3 distances, and the pipeline to 0.1 %. Nothing is tuned on run 2.
- **New negative control:** `--model uncorrected` (model 1, the run 1 model) must fail run 2's median check.
- **Capture as run 1**, with one instruction added: after each short beep, hold steady for the second the burst takes.

### Run 2: `192124-73b2` (2026-11-15, model 2): cannot judge, and per frame it would fail

- **Verdict:** cannot judge. 43 of 48 frames were judged, but at only 2 distances (3 needed).
- **Model 2:** median −0.5 % (passes 1 %), maximum 5.8 % (fails 2 %). The pipeline matches to 3e-8.
- **Control `--model uncorrected` (model 1):** median +11.7 %, maximum 18.2 %, so it fails as it must. The offset removes most of the bias.
- **Per burst:**

  | Burst | Board scale within the burst | Reported focus | Model 2 error |
  |---|---|---|---|
  | 1 | 93 to 113 µm per px (moved ~2.3 cm) | 7.88, 7.43, 6.82 D | +5.8 % down to −2.5 % |
  | 2 | 113 to 130 µm per px (moved ~2 cm) | 6.44, 5.99 D | +4.8 % down to −2.5 % |
  | 3 | 151.4 to 152.1 µm per px (steady) | 5.14 D, all 16 frames | −3.8 to −4.2 % |

- **The offset is not constant enough.** The focus that fits the board, minus the reported focus, for each settled stretch:
  - run 1: 0.82, 0.83 and 0.82 D (1 burst each) and 0.85 D;
  - run 2: 0.82, 0.78 and 0.59 D. The 0.59 D is the steady burst 3, at 0.008 D spread.
  - While the phone moves, the offset reaches 1.0 to 1.1 D, because AF lags.
  - So continuous AF stops anywhere within about ±0.15 D (0.25 D seen) of the board, inside its ±0.7 D depth of field. The reported focus is then that far from the board's distance.
- **Consequence:** scale from AF focus is good to about 0.2 D / D per frame: about 2.5 % at 12 cm and 4 to 5 % at 20 cm. The contract's 2 % per frame cannot be met this way on the Note8, whatever the offset.
  - This is a measured limit of the method, not a fitting problem. δ is not refitted on run 2.
  - Results: `microscope_scale_20261115_192124-73b2.json`, `microscope_scale_check_20261115_192124-73b2_calibrated.json` and `..._uncorrected.json`.
- **Status:** the app's scale bar (model 2) is an approximate scale, about ±5 % at 10 to 20 cm, and has not passed the contract. To be measurement-grade, the distance must come from something sharper than the AF stopping point. Candidates:
  - a manual focus sweep with the sharpness peak fitted (depth from focus, plan 3.3/3.6), which needs its own lens-map calibration;
  - an object of known size in view;
  - pose from the camera 0 + 2 rig, or from structure from motion (the fusion line).
- **Decision (Foad, 2026-11-15):** accept the approximate scale (about ±5 %) for now and go on to fusion (`align` next). The contract stays not passed, and the readout must be shown as approximate. A precise scale comes back later through the rig, structure from motion, or a focus sweep.
