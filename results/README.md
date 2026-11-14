# Device evidence

One folder per phone model. Every file here is written by a tool (`tools/probe/run_probe.py`, or adb itself for raw captures), never by hand. Device identifiers (adb serial, IMEI) are not recorded.

| Phone | ROM | Probe | Gate 1 cross-check | Dual physical streams |
|---|---|---|---|---|
| Galaxy Note8 SM-N950F (Exynos 8895, Mali-G71) | LineageOS 20.0 unofficial, Android 13 | [run 222940-c2f3](sm-n950f/probe_20261113_222940-c2f3.json), 2026-11-13 | **pass**, 16 fields agree, 0 disagree | not applicable: no logical multi-camera exposed |
| Galaxy Note10 SM-N970F (Exynos 9825, Mali-G76) | stock One UI, Android 12 | not run yet | not run yet | not run yet |

## What the Note8 run established (2026-11-13)

- The camera service exposes exactly two cameras, 0 (back, FULL, f = 4.3 mm) and 1 (front, LIMITED, f = 2.95 mm). Every ID from 0 to 127 was tried; none is hidden. The phone's second rear camera (telephoto) is therefore not reachable by any app on this ROM; that is a property of this LineageOS camera HAL, not of the hardware.
- Back camera: minimum focus distance 10 diopters (10 cm), focus distance calibration CALIBRATED, RAW and MANUAL_SENSOR capabilities. `LENS_POSE_TRANSLATION` and `LENS_INTRINSIC_CALIBRATION` are not published on either camera.
- A 1440x1080 YUV stream works on both cameras (42 and 39 frames in 2 s, about 20 fps). The HAL does not answer `isSessionConfigurationSupported` (query not supported), and `getConcurrentCameraIds` returns no sets.
- Compute inventory (not yet exercised): OpenGL ES 3.2 on Mali-G71, Vulkan 1.0.3, `libOpenCL.so` present and on the vendor public-library list, NNAPI not deprecated at API 33.

## Note8 telephoto: hidden by the HAL count, reachable underneath (2026-11-14)

`android/halprobe` loaded Samsung's camera module directly as the shell user ([halprobe_20261114.json](sm-n950f/halprobe_20261114.json), [32-bit](sm-n950f/halprobe32_vendor_20261114.json)). It reports `get_number_of_cameras` = 2 but answers for more IDs:

| HAL ID | Facing | Focal length | Sensor | Pixels | Meaning |
|---|---|---|---|---|---|
| 0 | back | 4.3 mm | 5.645 x 4.234 mm | 4032x3024 | wide (sensor 32) |
| 1, 2 | front | 2.95 mm | 4.002 x 3.006 mm | 3264x2448 | front and its alias |
| **3**, 50 | **back** | **4.2 mm** | **3.2 x 2.4 mm** | 4032x3024 | **telephoto** (reads `rear2_sensorid`, sensor 33) and its alias |
| 20 | back | 4.3 mm | 5.645 x 4.234 mm | 4032x3024 | wide alias |

All other probed IDs (4-7, 21-23, 51-53) return -19. The camera shim ([docs/units/camera-shim.md](../docs/units/camera-shim.md)) loaded by the 32-bit probe reports 3 cameras with camera 2 = the telephoto ([halprobe32_shim_20261114.json](sm-n950f/halprobe32_shim_20261114.json)). Installing it into the camera provider needs root and has not been done yet.

## Superseded runs

The first Note8 run (222822-685e) produced invalid JSON: `android.util.Rational` extends `Number` and was written raw as `1/2`. Fixed in `CharacteristicsDump.convert` and guarded in `Json` (non-JSON number text is quoted), with a regression test. That run's files were not committed.
