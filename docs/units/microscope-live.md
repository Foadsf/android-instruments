# Unit: microscope-live

- **Stage:** 4 (first thin app over camera 2), ahead of the Stage 6 MVP
- **Path:** `android/microscope` (new Gradle module), pure logic in `android/microscope/src/main/java/.../core`
- **Ported from:** "new". Camera opening follows `android/probe` `StreamTrials.kt`; lens description and sharpness ideas from android-microscope `Lens.kt` and microtopos `focus.py`, one function at a time.

## Why this shape

The Note8 camera 2 bridge (`docs/units/camera-bridge.md`) accepts exactly **one** output stream (`bridge.c` rejects `num_streams != 1`) and does not yet apply focus, zoom or exposure requests: HAL1 runs with its defaults. The reference android-microscope app always opens two streams (preview plus full-size YUV) and drives manual focus, so it cannot run on camera 2 as it is. This unit is the smallest app that works within those limits: one YUV stream, viewed and saved by the app itself.

## Contract

- **Input:** camera ID (default: `2` when listed, else the first rear camera; overridable by intent extra `camera`), one `YUV_420_888` stream. Sizes are tried 4:3 first (the sensor's full field), largest first, up to 1920x1440, walking down until a session configures: the bridge only accepts HAL1 preview sizes. On the Note8 camera 2 refuses 1920x1440 and accepts 1440x1080.
- **Output on screen:** the live picture, a CPU-side digital zoom (1x, 2x, 4x centre crop, since the bridge ignores `SCALER_CROP_REGION`), and three readouts: camera ID and size, measured frame rate, centre sharpness score.
- **Output on Save:** a raw burst for the fusion units (plan Stage 8): `files/captures/<stamp>/frame_NN.yuv` (N consecutive frames, default 16, packed I420 at full stream size, no ISP re-encode), one `preview.png` (luma), and `burst.json` with camera ID, size, per-frame sensor timestamp, frame rate over the burst, sharpness score, and the result's `LENS_FOCUS_DISTANCE` / `CONTROL_AF_MODE` per frame as reported (null when absent). Memory: 16 x 3.1 MB at 1920x1080, written as frames arrive.
- **Output on Pair:** the same burst from camera 0, then from camera 2 (the bridge cannot stream both at once), in one folder, so the same static scene exists from the wide and the telephoto for `cross_camera_register` and `multicam_fusion`.
- **Run mode for evidence:** started over adb with the extras `run_id`, `cameras` (comma-separated, in order), `stream_ms` and `burst`: per camera it opens, streams, records a burst, closes; writes `files/microscope_live_<run_id>.json` and finishes. `tools/microscope/run_live.py` installs, starts, waits, pulls the report to `results/<model>/`, pulls the raw bursts outside the repo (`note8_camera_stack/bursts/`), and writes `microscope_live_checks_*.json` with the verdict. In run mode the activity shows over the lock screen (it does not unlock): behind the lock screen the app counts as background and the camera service refuses the next camera.
- **Burst capture:** buffers are allocated up front (cap 32 frames, 75 MB at 1440x1080); during a burst the image thread only copies; files are written after the last frame, so the burst frames are consecutive.
- **Preview:** a separate thread converts its own copy of the newest frame; frames it is busy for are not previewed, so the preview cannot slow the stream.
- **Errors:** an open or configure failure is shown on screen and written to the run JSON with the exception text; never a silent black view (the microtopos failure).

## Pure functions (JVM-tested)

| Function | Contract |
|---|---|
| `pickCamera(ids, facing, requested)` | requested if listed; else `2` if listed; else first rear; null if none |
| `sizeCandidates(sizes, maxPixels)` | 4:3 sizes largest first, then the others largest first, all within the cap; empty if none fits |
| `FrameRate.add(tsNs)` / `.fps(windowNs)` | frames per second over a sliding window of sensor timestamps |
| `sharpness(luma, w, h, stride, roi)` | mean squared Laplacian over the ROI, a focus measure |
| `cropForZoom(w, h, zoom)` | centred integer rectangle of size w/zoom x h/zoom |
| `packI420(planes, w, h)` | YUV_420_888 planes with any row and pixel stride to packed I420; byte-exact on constructed odd-stride buffers |

## Oracle

- `sharpness`: a synthetic checkerboard and the same board blurred with a Gaussian generated in the test (not by the code under test). The score must order them and rise monotonically as blur falls. Cross-check: on three device frames, the same score computed by `cv2.Laplacian(...).var()`-style NumPy code in `tools/microscope/` agrees within 1 %.
- `FrameRate`: timestamps generated at a known 30.0 fps with jitter.
- Device: the camera 2 frame is the telephoto, checked with the NCC scale search against a wide frame (the method in `camera-bridge.md`: ratio near 1.87).

## Thresholds (declared before the first run)

| Check | Threshold | Source of the number |
|---|---|---|
| frame rate on camera 2, 10 s run | ≥ 20 fps, 0 capture failures | bridge measured ~29 fps (`camera-bridge.md`); other cameras' rates are recorded, not judged |
| `FrameRate` on synthetic 30 fps | 30.0 ± 0.3 | definition |
| sharpness ordering | sharp > blur σ=1 > blur σ=3, strictly | definition |
| burst of 16 on camera 2 | 16 frames saved, timestamps strictly increasing, no gap > 2 frame periods | bridge rate |
| device sharpness vs NumPy | within 1 % | float rounding |
| camera 2 vs wide scale (NCC) | 1.87 ± 0.10 | `camera-bridge.md` daylight result |

## Negative control

- `pickCamera` with `2` absent must not return `2`.
- A constant (flat grey) image must score sharpness 0; swapping sharp and blurred inputs must fail the ordering test.
- Run mode on a camera ID that does not exist must write a run JSON with an open error and exit code 1 from `run_live.py`.
- A slow camera 2 stream, a burst with a gap, non-increasing timestamps, a short burst, an empty report, and an app sharpness 5 % off NumPy must each fail the host checks (`tools/microscope/test_microscope_tools.py`).

## Not in this unit

Manual focus (bridge milestone 4), a second full-size stream, and the fusion itself (burst merge, super-resolution, cross-camera registration and fusion, gyro prior: plan Stage 8). This unit only supplies their raw input, so they can be built and judged on real Note8 bursts.

## Device evidence

Note8 (SM-N950F, LineageOS 20, shim persistent), 2026-11-14 evening, phone lying still facing a dark, featureless surface. Host: 20/20 JVM tests (they failed first against stubs), 10/10 tool tests.

| Run | What | Result | Files (`results/sm-n950f/`) |
|---|---|---|---|
| 1 | camera 2, 10 s + burst | app crashed: the burst timed out at 13 frames, then a late frame hit the closed writer. Fixed: late frames are ignored; buffers preallocated; files written after the burst | none (no report) |
| 2 | camera 2 | **fail**: stream 5.1 fps; 195 ms per frame on the image thread (preview conversion). Burst itself 28.2 fps | `microscope_live_*_174838-2342.json` + checks |
| 3 | camera 2, 10 s + burst | **pass**: 25.1 fps, 239 frames, 0 failures; burst 16/16 at 26.5 fps, largest gap 1.67 periods; sharpness app 47.1976 vs NumPy 47.198 (rel < 1e-6) | `*_175008-fcca.json` |
| 4, 5 | pair 0 then 2 | **fail**: camera 2 refused, "Access ... has been restricted" (AppOps): the lock screen covered the app, so it counted as background. A retry did not help (it is not timing) | `*_175042-2bf0.json`, `*_175309-f581.json` |
| 6 | camera 2 alone | **pass**: 22.1 fps | `*_175336-0219.json` |
| neg. control | camera 9 (does not exist) | **fail as required**: error recorded ("unknown device 9"), exit code 1 | `*_175735-1b52.json` |
| 7 | pair 0 then 2, over the lock screen | **pass**: camera 0 14.8 fps (exposure 60 ms in the dim scene caps it near 16.7 fps; recorded, not judged), camera 2 23.1 fps; both bursts 16/16, largest gap 0.89 periods | `*_175526-0da1.json` |

Observed on camera 2 through the bridge: `CONTROL_AF_MODE` 4 (continuous picture), and no `LENS_FOCUS_DISTANCE` or exposure in the results: the bridge does not report them yet (bridge milestone 4). Camera 0 reports focus 0.31 D and exposure.

**Not verified yet:**
- That camera 2's frames in this app are the telephoto by image scale. On this dark scene the NCC check is meaningless: its own negative control (frame 0 vs frame 8 of the same camera) gave scale 2.24 at NCC 0.45, where it should give 1.00. The bridge's identity as the telephoto rests on `camera-bridge.md` (kernel log: only the telephoto sensor starts; daylight NCC 1.87). To close: `run_live.py --cameras 0,2` with the phone aimed at a lit, textured scene, then `ncc_scale.py` on frame 0 of each burst.
- The live preview on screen and the Save and Pair buttons by hand (run mode exercises the same code paths, without the UI).
- The clip-on lens test (Foad's hands).
