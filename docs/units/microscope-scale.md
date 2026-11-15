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
- **Nominal focal length** (4.30 mm and the sensor's nominal pitch, without the calibration): about 3.5 % off at 40 cm and about 7 % at 10 cm, which must fail.
- **Wrong board size** (a spec claiming 21 px squares) must fail every frame by about 5 %.

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

None yet.
