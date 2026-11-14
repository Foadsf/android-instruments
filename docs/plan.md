# Galaxy phone as microscope, 3D scanner and compute device: review and step-by-step rebuild plan

13 November 2026. Based on a read-only review of eight repositories (the seven named plus `microtopos`, which the chats cover) and the 24 chat transcripts in `chats/`. Nothing was built or run for this review; every "works" below means a test in the repo asserts it, and every "on device" means a result Foad pasted from a phone.

## 1. What the review found

### The one-paragraph verdict

The algorithms are not the problem. Three of the repos already contain clean, Android-free cores with real known-answer tests. The problem is that almost nothing has ever been verified on the phone, the same five algorithms were rewritten four times in four places, and each rewrite was a whole app at once. Across all eight repos there is exactly one device run on record for the phone camera work (floss-android-microscope on the Note10: 1,263 s for 16 frames, then a crash on a 110 MB bitmap). The rebuild should therefore be organised around device evidence, not around features.

### Where each repository stands

| Repo | Local clone | Core separable from Android? | Tests that check a number against a known answer | Ever run on a phone? | Keep as |
|---|---|---|---|---|---|
| android-microscope | `~\.gemini\antigravity\brain\d365…\scratch\refs\android-microscope` | Yes: `imaging/` (2,540 lines Kotlin) has no `android.*` import | 23 JVM tests: alignment < 0.1 px, SR +2 dB, focus stack +3 dB, Sa/Sq, optics vs hand calculation | No (README says tilt mode unverified) | **Reference for every microscope algorithm and its test** |
| floss-android-microscope | `Downloads\20261107\Android_microscope` | Partly (807-line C++ god-file mixes JNI and maths) | None | Yes, once: 1,263 s, then crash | Retire. Several outputs are fabricated (constant "SNR gain", "Vulkan" that is GLES, "NNAPI" that is a fixed sharpen, non-metric SfM) |
| parallax | `~\.gemini\…\scratch\refs\parallax` | Yes: `cpp/core` (1,950 lines) builds on a desktop with system OpenCV | One end-to-end ray-traced scene test (pose, scale, gravity, dense error), but CI thresholds are 10 to 40 times looser than the README claims | No | **Reference for SfM, BA, dense stereo**; split its one test into per-stage tests |
| android-multicam | `Downloads\20261110\Android_camera\MultiCamSuite` | Yes: `engine.hpp` compiles with plain g++, but is a 1,033-line god-file holding three engines | 6 host tests: gyro integration, burst shift < 0.15 px, stereo depth < 4 %, closed sphere mesh | No | **Reference for camera-pair selection, IMU, TSDF**; best example of small per-function tests |
| android-hpc | `Downloads\20261107\Android_HPC\android-hpc` (fast-forwarded today) | Yes: `Backend`/`Execution` interface, `hpc_cli` runs over adb | fp64 oracle, negative controls on the verifier, odd sizes, CI on lavapipe and PoCL | Yes, 0.1.x on Note8 and Note10 (all five backends); 0.2.0 not yet | **Foundation: the compute layer and the verification pattern** |
| neural-enhance-bench | `Downloads\20261105\android_CNN_VLM` | Seam exists (`processTile`) | None | No | Retire. It contains no neural network: "ESPCN/NAFNet" are hand-written 3x3 kernels, PSNR is measured against its own input. Keep only the tiler idea |
| sfm-snr-mfsr | `Downloads\20261105\SFM_SNR\sfm-snr-mfsr` | No: one 1,864-line file (checked in twice, byte-identical); the README's `include/` headers do not exist | Adjoint test runs against its own copy of the operator, not the shipped one | No | Retire. Keep the forward/adjoint operator maths as a later unit |
| microtopos (desktop) | `Downloads\20261105\microtopos` | Yes: only `gui/` imports Qt | Self-test against a simulator (SFF r ≥ 0.9, slope 1 ± 0.05), sub-pixel registration < 0.05 px, Hypothesis property tests, CI on 3 OSes | Yes, real microscope: self-test 30/30, but live use showed black view, diagonal stitching, heights in "frames" | **Python oracle for the microscope algorithms**; its own line continues |

### Hard facts from the chats that the plan must respect

- **The phone is a Note10 SM-N970F, Exynos 9825, Android 12, stock and unrooted** (from Foad's own app log). The second, rooted phone is called a Note8 SM-N950F only by Gemini; Foad never typed the model. The "S10 / Exynos 9820" in other chats is wrong.
- **From `dumpsys media.camera` on the Note10:** HAL 3.5 legacy; RAW on IDs 0, 2, 50; logical cameras 20 {0, 52, 2}, 21 {52, 0}, 23 {0, 2}, all CALIBRATED sync; **`lens.poseTranslation` and `intrinsicCalibration` are absent.** Both parallax (scale from `LENS_POSE_TRANSLATION`) and android-multicam (falls back to a hard-coded 15 mm baseline) therefore have no source of metric scale on this phone as written. Stage 1 below confirms this per physical camera.
- **Third-party dual physical streams were never proven.** Only Samsung's own camera app was seen configuring two streams on logical 20. The minimal test app was written several times and never run.
- **The library that was reverse-engineered was the wrong one** (32-bit, Galaxy S6 era, downloaded from GitHub). All HAL patch offsets in those chats are void. Foad has since said he prefers not to patch.
- **Optics set a hard floor.** Without an added lens, magnification is about 0.05x and the realistic resolution limit is 60 to 80 µm, not the 15 to 20 µm that one requirement set asked for.
- **NNAPI is deprecated from Android 15**; `libOpenCL.so` must be loaded with `dlopen`; mobile GPUs have no useful fp64.
- **The failure pattern was the process:** one-shot "build the whole app" requests, then "is this the best you can deliver?", each round confessing the previous round's fake features, almost none run on the phone.

## 2. Principles for the rebuild

1. **One unit, one contract, one test, written before the code.** Each unit is a folder with a README stating its input, its output, its oracle and its pass thresholds. The thresholds are copied from the existing tests above, not invented afresh.
2. **The oracle must not share code with what it checks.** The microtopos self-test was partly circular because the simulator used the same optical model as the reconstruction. Synthetic scenes are generated by an independent renderer; ported algorithms are checked against the Python reference (microtopos) or fp64 (android-hpc pattern).
3. **"Works on the phone" means a results file in the repo.** Every device test writes `results/<device>/<unit>_<date>.json` with the raw numbers. No file, no claim.
4. **C++17 core, Kotlin only for Camera2 and UI.** The compute ambitions (Vulkan, OpenCL) and the three strongest repos all point to a host-testable C++ core under CMake. The Kotlin algorithms from android-microscope are ported, and their 23 tests become the acceptance tests of the port.
5. **CPU first, accelerate only what a profile names.** The 818 s alignment on the Note10 was AKAZE recomputed per frame, not a missing GPU.
6. **Size limits enforced in CI:** file ≤ 400 lines, function ≤ 60 lines, no `android.*` or JNI include in `core/`.
7. **One repository, many small modules.** The seven repos stay as frozen references (archive them on GitHub with a README pointer); new work goes into one new monorepo so units can share the buffer type and the test harness.

## 3. Step-by-step plan

Each stage ends at a gate. Do not start a stage before the previous gate passes; within a stage the units are independent and can be done in any order or in parallel.

### Stage 0: freeze and set up (half a day)

- Archive the seven GitHub repos (read-only) with a one-line README pointer to the new repo.
- Create the new monorepo: `core/` (C++17, CMake, ctest, no Android), `android/` (Gradle, thin apps), `tools/` (fixture generators), `results/` (device evidence), `docs/units/` (one contract per unit).
- CI from day one: host ctest, lavapipe + PoCL for compute (copy android-hpc's workflow), APK build, `INTERNET` permission check (copy from android-microscope), size-limit lint.
- **Gate 0:** an empty unit with one passing and one deliberately failing test proves CI catches failures.

### Stage 1: device facts, before any algorithm (1 to 2 days)

One small probe app, built from parallax `DeviceProbe`/`CameraProbe` plus android-hpc `discoverBackends()`. It writes one JSON per phone with:

- every camera ID, its physical IDs, facing, focal lengths, `LENS_INFO_MINIMUM_FOCUS_DISTANCE`, focus calibration quality, sensor size and pixel array, capabilities, RAW availability, and whether `LENS_POSE_TRANSLATION`, `LENS_POSE_ROTATION`, `LENS_INTRINSIC_CALIBRATION`, `LENS_DISTORTION` are populated, read **per physical camera** with `getCameraCharacteristics("<physical id>")`;
- `isSessionConfigurationSupported` for the candidate dual-stream pairs on logical 20, 21 and 23 at 1440x1080, 1920x1080 and full size, and then an actual open: did `onConfigured` fire and did frames arrive on both streams within 2 s;
- compute backends available (CPU cores, Vulkan version, OpenCL via dlopen, GLES 3.1, NNAPI or LiteRT delegate).

Run it on the Note10 and the second phone. Commit the JSON as golden fixtures.

**Gate 1:** both JSON files exist; three fields are spot-checked against `adb shell dumpsys media.camera`; the dual-stream question has a yes or no for each pair. This single file settles the camera-ID confusion and decides whether the 3D scanner can use simultaneous streams or must fall back to sequential capture with a ChArUco-calibrated rig.

### Stage 2: foundation library, host only (2 to 3 days)

| Unit | Contract | Oracle and threshold | Source to reuse |
|---|---|---|---|
| `image` | `Plane<T>` with stride, `ImageView`, `YuvView` over Y/U/V planes with row and pixel stride | round-trip copies, odd strides | new, informed by android-microscope `Images.kt` |
| `io` | read and write PGM/PNG/NPY/JSON for fixtures | byte-exact round-trip | new |
| `verify` | oracle + tolerance + verdict (ok, maxAbs, maxRel, badIndex) | negative control: corrupt element, NaN, wrong length must each fail | android-hpc `verify` and its tests |
| `metrics` | PSNR, SSIM, NRMSE against a *true* reference | known pairs, identity = infinite PSNR | android-microscope, fixed (neural-enhance-bench measured against its own input) |
| `synth` | independent scene renderer: textured plane, sphere, tilted sinusoid, focus stack with a Gaussian-defocus PSF that is **not** the one the SFF unit assumes | analytic values | microtopos `simulator.py` as a start, then decoupled |

**Gate 2:** all foundation tests pass in CI; the verifier's negative controls fail as they should.

### Stage 3: microscope algorithm units, host only (1 to 2 weeks)

Single camera, no multi-camera blocker, and the best-tested source code: this is the shortest path to a verified result on the phone. In dependency order:

| # | Unit | Input to output | Acceptance (copied from existing tests) | Port from |
|---|---|---|---|---|
| 3.1 | `yuv` | YUV_420_888 planes to luma float / RGB | constructed buffers with odd row and pixel strides, exact | android-microscope `FrameCopy`, multicam `addYuv` |
| 3.2 | `pyramid` | plane to Gaussian and Laplacian levels | exact reconstruction to 1e-3 | android-microscope `Pyramid.kt` |
| 3.3 | `focus_measure` | luma to modified-Laplacian and Tenengrad maps | equals microtopos `focus.py` on the same fixtures to 1e-5 | microtopos, android-microscope |
| 3.4 | `align` | (reference, moving) to translation, then similarity, then homography | synthetic warp recovered < 0.1 px; translation < 0.05 px; cross-checked against OpenCV ECC on desktop | android-microscope `Align.kt`, microtopos `registration.py` |
| 3.5 | `focus_stack` | frames + warps to all-in-focus image | ≥ 3 dB better than the best input frame | android-microscope `FocusStack` |
| 3.6 | `sff` | registered stack + focus distances in diopters to height map in µm, confidence, valid mask | sphere and tilted plane from `synth`: r ≥ 0.9, slope 1 ± 0.05, ≥ 70 % valid | android-microscope `DepthFromFocus`, microtopos `sff.py` |
| 3.7 | `burst_sr` | YUV frames + warps to image at scale s | ≥ 2 dB over single frame, ≥ 1 dB over a still burst; memory cap for 12 MP declared and tested | android-microscope `SuperResolution`, multicam `MicroscopeEngine` |
| 3.8 | `metrology` | height map + pixel size + unit to Sa, Sq, Sz, Sdr; ISO 16610 Gaussian filter | analytic sinusoid; filter transmission 0.50 at cutoff | microtopos `metrology.py`, android-microscope `AreaParameters` |
| 3.9 | `optics` | lens metadata + focus distance to magnification and µm per pixel | hand calculation: 0.0568x, 24.6 µm/px for the Note10 main camera at its stated focus | android-microscope `Optics` |
| 3.10 | `export` | height map / point cloud to GSF, PLY, STL | byte round-trip | android-microscope `Gsf`, parallax `io` |

**Gate 3:** every unit green on host; each unit's README lists its thresholds and its source.

### Stage 4: the camera as a frame source, on the phone (3 to 5 days)

- `FrameSource` interface in Kotlin with two implementations: a fake that serves `synth` fixtures, and Camera2.
- Camera2 manual-focus controller: request a focus distance, wait until `LENS_STATE` is stationary and AE is locked, then expose; record requested and reported `LENS_FOCUS_DISTANCE` and the timestamp for every frame (android-microscope `MicroscopeCamera` already does the waiting; floss-android-microscope did not).
- Memory budget: frames held as YUV, never as full-size bitmaps; viewer downsamples.
- **Gate 4 (device):** `results/note10/frame_source_<date>.json` shows a 16-frame focus sweep with no dropped frame, reported focus within a stated tolerance of requested, and the repeatability of focus over five sweeps. This is the first time the lens is measured rather than assumed.

### Stage 5: compute layer under the core (in parallel with Stage 3 or 4)

- Take android-hpc's `Backend`/`Execution` dispatch and generalise `Problem` from benchmark kernels to image operators.
- First operators: 3x3 convolution and the focus measure from 3.3, verified against the CPU unit (which is itself verified), plus the existing fp64 oracle.
- Run 0.2.0 and the new operators on the Note10 through `hpc_cli` over adb.
- **Gate 5 (device):** results file with per-backend timing and verdict. Only after this does any Stage 3 unit get a GPU path, and only if the Stage 6 profile shows it is the bottleneck.

### Stage 6: first vertical slice, microscope MVP on the Note10 (1 week)

Wire `FrameSource` to 3.4, 3.5, 3.6, 3.8 and a minimal viewer. No SfM, no SR yet.

- Target: an object with a known dimension and known relief (a steel ruler for scale, a coin edge or a machined step for height).
- **Gate 6 (device), thresholds declared before the run:** scale from `optics` agrees with the ruler to within a stated percentage; a 16-frame sweep processes in under a stated time (for reference, the old app took 1,263 s); peak memory under a stated limit; height of the step within a stated tolerance. Results file committed with the raw stack so the run can be replayed on the host.

This is the first point at which the project has a working instrument. Burst SR (3.7) is added next, judged against the same captured stack.

### Stage 7: 3D scanner line (2 to 3 weeks, only after Gate 6)

The route depends on Gate 1:

- **If dual streams work on logical 20/21/23:** stereo pair capture with timestamp pairing (multicam slot logic as a pure unit with synthetic timestamp tests).
- **If they do not:** sequential capture with the main camera only, scale from a printed ChArUco board or a marker.
- **Either way, metric scale comes from a ChArUco `stereoCalibrate`**, not from `LENS_POSE_TRANSLATION` (absent on the Note10 per the dumpsys) and never from a hard-coded baseline.

Units, each with its own synthetic test (splitting parallax's single end-to-end test): `camera_model` (characteristics to intrinsics, JVM test on the Stage 1 JSON), `features` (takes a buffer, not a file path), `two_view_pose` (rotation and translation-direction error on synthetic points), `triangulate`, `bundle_adjust` (including the scale gauge freedom that one review found missing), `scale` (rig or marker), `gravity`, `dense_stereo` (on multicam's plane fixtures: < 4 % depth error), `tsdf_mesh` (closed sphere, Euler characteristic 2), `writers`. Tighten CI thresholds to what the README claims (pose RMS < 0.5 mm, scale within 0.5 %) instead of today's 5 mm and 5 %.

**Gate 7 (device):** scan of an object of known size; dimension error stated against a caliper.

### Stage 8: multi-frame and multi-camera fusion for image quality (core goal)

Amended 2026-11-14 (Foad): fusing frames and camera sensors to raise SNR and resolution is a major goal of the project, not an optional extra. It can start as soon as `align` (3.4), `metrics` and a frame source that saves raw bursts exist (`docs/units/microscope-live.md`); it does not wait for the scanner line. The Note8 now exposes the wide (camera 0) and the telephoto (camera 2) as separate cameras, so both can be captured from one scene. They cannot stream at the same time through the bridge: capture is sequential, which suits a static specimen.

| Unit | Input to output | Oracle (independent of the code under test) |
|---|---|---|
| `burst_merge` | N aligned YUV frames to a denoised frame | SNR gain close to √N on a static scene; truth is the mean of a much longer burst; measured on the flat patch of a test chart |
| `burst_sr` (3.7) | N frames with sub-pixel shifts to an image at 2x | wide-camera burst at 2x scored against the **telephoto** frame of the same scene, a true optical reference about 1.9x finer |
| `cross_camera_register` | wide and telephoto frames to a warp (homography, then a parallax-aware flow at close range) | synthetic pair with known warp; on device, residual after warping |
| `multicam_fusion` | registered wide + telephoto bursts to one image: telephoto detail in its field, wide SNR and field around it | PSNR/SSIM against a reference captured with more frames; no gain may be claimed against the fused image's own inputs |
| `motion_prior` | gyro samples on the camera clock to a rotation between frames | gyro integration test from android-multicam; used only as the alignment's starting guess and to drop frames taken while the phone moves, never as the measurement |

Limits stated up front: at microscope distances with a clip-on lens only one camera looks through the lens, so there the gain comes from multi-frame fusion on that camera; cross-camera fusion pays at macro and normal distances, and for the scanner.

- `tiler`: tile, overlap, Hann blend; identity tile function must reproduce the input exactly.
- Real models only through LiteRT (not NNAPI), with fidelity-trained (L1) networks, judged on the Stage 6 captured stacks against a true reference, never against their own input.
- `mfsr_operator`: forward A = D·H·W and its adjoint from sfm-snr-mfsr, with the dot-product test run on the shipped operator.

### Stage 9: the super-app

Only now: one Android app with three modes (microscope, scanner, benchmark) over the same `core/`, `FrameSource`, compute layer and results format. microtopos stays a separate desktop product; optionally it later calls the same C++ core through pybind11, which would also make it the cross-check for every port.

## 4. How to work with AI agents from here

- Give an agent one unit: its contract, its test with thresholds already written and failing, and the file it may port from. Never "build the app".
- The agent is done when CI is green and, for device units, when a results file exists. Its own summary is not evidence.
- Each unit is one pull request under the size limits. A change that touches more than one unit is split.

## 5. Decisions only Foad can make

1. **Optics.** Without an added lens the phone microscope is capped at roughly 60 to 80 µm. Accept that limit for the MVP, or add a cheap clip-on macro or reversed lens (the plan does not depend on the choice until Gate 6).
2. **microtopos base line.** `main` (v0.8.x: verdict, units, objectives) and `feat/copilot-diagnostics-and-resolution` (logging, validation, pose graph, 22 tests) each fixed the same review findings independently, 7 and 6 commits apart, and will conflict in `main_window.py`, `mosaic.py`, `selftest.py` and `live.py`. Pick one as the base and cherry-pick from the other.

Everything else above is a recommendation I would execute as written.
