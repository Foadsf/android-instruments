# Unit: HAL1-to-HAL3 camera bridge (Note8 telephoto)

- **Stage:** 1 (device capability), prerequisite for any telephoto use on the Note8
- **Paths:** `android/hal1probe` (proof), `android/camshim` (the bridge will live here), `core/camera_params`, `core/camera_idmap`

## Why

On the Note8 (LineageOS 20) the HAL3 library cannot stream the telephoto (see `docs/re/note8-telephoto-dual-mode.md`). Samsung's HAL1 library can: on 2026-11-14 `hal1probe` (root, camera provider stopped) opened the telephoto with `open_legacy("3", HAL1)` and received **89 NV21 1920x1080 preview frames in 3 s (about 30 fps)**, a real image of the same scene as the wide camera at about 1.7x, kernel log `sensor ID(33)`, `REAR_2ND(Tele)`. Camera 0 through HAL1: 79 frames in 3 s. No preview window was needed. Neither run crashed.

Dual mode (`open_legacy("20")`, main 0 + tele 3) opens both cameras but `start_preview` fails with -19 at `[Fusion] DUAL_PREVEIW m_initDualSolution() failed!!`, because Samsung's fusion plugins `libdualpreview_interface.so` and `libdualcapture_interface.so` are not on this ROM (only `libuniplugin.so` is).

## HAL1 facts the bridge relies on (static analysis, confirmed on the phone where noted)

- `open_legacy(id, any non-zero version)` gives a HAL1 `camera_device_t`; IDs `"0"`, `"1"`, `"3"` (`"50"` = 3, `"90"` = 2) open single cameras, `"20"` opens dual. Confirmed for 0 and 3.
- Module `set_callbacks` must be called before opening: the HAL reports torch status during open (NULL callbacks crashed at offset 4). Confirmed.
- With no preview window the HAL allocates internal preview buffers and delivers frames by `data_cb(CAMERA_MSG_PREVIEW_FRAME)` with memory obtained through the client's `get_memory(ion_fd, size, 1, user)`, released right after the callback. Confirmed.
- `set_preview_window(preview_stream_ops*)` makes the HAL render into client-provided gralloc buffers (buffer-manager type 2). Not yet exercised.

## Design

The shim keeps exposing framework camera 2. Instead of forwarding camera 2 to the vendor HAL3 device (which cannot stream it), the shim implements a HAL3 `camera3_device_t` itself for that ID and drives the vendor HAL1 device `"3"` underneath:

| HAL3 call | Bridge action |
|---|---|
| `get_camera_info(2)` | vendor HAL3 `get_camera_info(3)` (static metadata already correct: 4.2 mm, 3.2 x 2.4 mm) |
| `open` | vendor `open_legacy("3")`, `set_callbacks` |
| `configure_streams` | accept one YUV/implementation-defined stream; set HAL1 `preview-size` to its size (from HAL1 `preview-size-values`), `preview-format` to match |
| `process_capture_request` | queue the request's output buffer; a `preview_stream_ops` implementation hands queued gralloc buffers to HAL1 on `dequeue_buffer` and, on `enqueue_buffer`, returns them in `process_capture_result` with shutter timestamp and minimal result metadata (zero copy) |
| controls | map AF/AE/manual focus to HAL1 parameters (`focus-mode`, `focus-distance` equivalents) |
| `flush`, `close` | `stop_preview`, `release`, `close` |

Fallback if the `preview_stream_ops` path misbehaves: copy from the data callback into the HAL3 buffer (needs gralloc lock in the provider process).

## Milestones, each with its own device test

1. `hal1probe --window`: a `preview_stream_ops` backed by test buffers, to prove HAL1 renders through a window. Pass: frames enqueued at >= 20 fps.
2. Bridge skeleton: camera 2 opens, configures one 1920x1080 YUV stream, the probe app's `CONTROL` trial on camera 2 WORKS (>= 10 frames in 2 s).
3. Size and format coverage: every YUV size in camera 2's stream map either works or is removed from the advertised map.
4. Focus control mapped; verified by the reported lens position.
5. Dual (wide + tele): needs Samsung's fusion plugin or a stub that satisfies `m_initDualSolution`; separate decision.

## Milestone 1 result (2026-11-14): window path runs, buffers stay empty

`hal1probe ... 3 3 --window` with AHardwareBuffer-backed buffers: the HAL asked for format `0x11e` (Samsung private, two-plane NV21), usage `0x20933`, 9 buffers. `0x11e` cannot be allocated through the NDK, so the window fell back to `0x23` (YCbCr_420_888). The HAL dequeued and enqueued 85 buffers in 3 s, but every saved frame was all zeros (frames 1 and 30; also with the stride set to 1920). Log: `MCSC_PREVIEW ... exynos_v4l2_qbuf(...) fail (-1)`, `putBuffer() fail ... ret(-22)`. The ISP's preview output node rejects buffers that are not in its configured format, and the HAL hands them back unfilled. **Zero copy with framework-allocated standard YUV buffers does not work on this ROM.**

Way forward, found on the phone: the ROM ships the legacy gralloc module `gralloc.exynos5.so` behind `android.hardware.graphics.allocator@2.0-impl` / `mapper@2.0-impl` (passthrough). Through the gralloc0 interface (`hw_get_module("gralloc")`, alloc device `"gpu0"`, `lock`/`lock_ycbcr`):

- **1b.** Allocate the window buffers in the HAL's own format `0x11e` and verify the saved frame holds an image (zero copy inside the bridge's private buffers).
- **Copy path for the bridge.** Lock the framework's output buffer with the gralloc0 module inside the camera provider and copy each HAL1 frame into it (NV21 to the buffer's real plane layout).

## Dual mode with the stock fusion plugins (2026-11-14)

Source: Foad's own stock firmware backup `N950FXXUGDZEB` (Android 9) from his Drive, system image extracted with `tools/re/samsung_system_image.py`. LineageOS's `libexynoscamera.so` differs from stock only in build ID, build-date string and the compressed debug section (7 runs, same size); `libuniplugin.so` is identical. The three missing libraries (32-bit) were pushed to `/data/local/tmp/instruments/stocklib` and given to `hal1probe` alone through `LD_LIBRARY_PATH` (nothing on `/system` changed):

| File | SHA-256 |
|---|---|
| `libdualpreview_interface.so` | `d81b9de9b825e24cea750b1fb113d7e557a84b6a634f0fe8205f93e70d02a333` |
| `libdualcapture_interface.so` | `21f951a10805ac3eec9d9fd01c00ae33478859fe0ca63d167ae2ef1ac9d352c6` |
| `libdualcam_optical_zoom.so` (needs only `libOpenCL.so`) | `c7196103fa0bb23ff47f35eac64b050df1dc613223f5ecb93293753931d12c99` |

Results:

- Both plugins load (`dlopen(17:DualPreviewPlugin) is succeeded`).
- Without a window, dual `start_preview` crashes the process (not the phone) in `ExynosCameraGrallocAllocator::setBufferCount` (NULL allocator): dual mode needs a preview window.
- **With the window, dual mode runs: `start_preview` 0, 81 frames in 3 s, 24 fps by the HAL's own timestamps, and the frames hold a real image in the standard `0x23` buffers** (the fusion stage writes them, unlike the single-camera ISP path). Both cameras run: `CAM_ID(3)` starts, sensor 33 / `REAR_2ND(Tele)`, `DualPreviewSelector` pairs frames.
- **At `zoom=30` (2.0x) the output is still the wide camera, digitally cropped.** Log: wide `cropRect(1014, 570, 2006, 1128)`, tele zoom 1.0, sync type stays 1. Geometry agrees: the wall mark lands where a 2x crop of the wide frame predicts (about 1094, 468 vs observed 1060, 470) and not where the telephoto frame has it (1150, 710). Inference: Samsung's fallback (`setMasterLuxFBCond`, `setMasterDistanceFBCond`) kept the wide camera as master because the scene was dim and close; not yet tested in daylight at a distance.

### Daylight at a distance (2026-11-14, same session)

Same scene, phone held still, three back-to-back runs: dual `zoom=30 --window` for 8 s (241 frames, 29 fps by HAL timestamps, frame 150 saved), then the telephoto alone (`"3"`) and the wide camera alone (`"0"`). Similarity transforms by ORB + RANSAC (`scale_match.py`, scratch tool):

| Pair | Scale | Telephoto hypothesis | Wide 2.009x crop hypothesis |
|---|---|---|---|
| telephoto vs wide | 1.902 | (measured lens ratio on these streams) | |
| dual 2x vs telephoto | **1.008** (601/805 inliers, 0.2 deg) | 1.000 | 1.056 |
| dual 2x vs wide | **1.909** | 1.902 | 2.009 |

**In daylight at a distance, Samsung's dual mode at 2x outputs the telephoto, at 29 fps, into standard YUV buffers.** Indoors (dim, close) the same mode kept the wide camera, cropped, which matches Samsung's lux and distance fallback. Consequence for the bridge: dual mode gives zero-copy telephoto frames only when Samsung's fallback allows (bright, distant scenes); the single-camera HAL1 telephoto (`"3"`, data callbacks) is unconditional but needs the copy path. For microscope work (close range) the copy path is the one that matters.

## Dual-mode bridge as a HAL3 device (2026-11-14)

`android/camshim/bridge.c` (+ `bridge_meta.c`, `bridge_hal1.c`, `core/camera_bridge_queue`): framework camera 2 opens HAL1 `open_legacy("20")` with `zoom=30`, and the framework's output buffers become the HAL1 preview window. Plugins are preloaded from `persist.instruments.camera.plugin_dir` before the vendor module loads (its plugin thread looks for them at start-up; preloading at open time was too late: `DUAL_PREVIEW plugin load failed`). `persist.instruments.camera.bridge=0` falls back to the vendor's own HAL3 device.

Probe CONTROL trial on camera 2 (1440x1080 YUV), in order of fixes:

1. `configure` failed in the framework: `Camera HAL requested max_buffer count: 0`. A raw dump of `camera3_stream_t` showed **`usage` is 64-bit in this provider** (words 4-5 usage, 6 max_buffers, 8 data_space `0x08C20000` JFIF); `legacy_camera3.h` had `uint32_t` and every later field was shifted.
2. `start_preview` blocked 5 s and failed: HAL1 dequeues its whole set (9 buffers) inside `start_preview`, and the request thread was the one waiting. Now a starter thread runs it.
3. Configured, `start_preview` 0, **9 frames delivered, then nothing** (`results/sm-n950f/probe_20261114_*`, verdict PARTIAL_FRAMES). Window trace: the first 9 framework buffers are dequeued and filled; the 10th (a handle HAL1 never registered) is cancelled immediately, again and again (`Gralloc buffer collector has no Buffer`). **Samsung's HAL1 only fills the 9 buffers it registered at start; the framework circulates more than 9 (HAL max_buffers + the consumer's).** Zero copy into framework buffers therefore does not work for a general consumer.

### Copy path (2026-11-14): camera 2 WORKS

HAL1 now fills a private pool (`bridge_pool.c`: 9 `AHardwareBuffer` `0x23`, usage camera write + CPU read + the HAL's `0x20933`). On each filled frame the bridge takes the oldest pending request, waits its acquire fence, and copies the frame into the framework buffer with `core/yuv_copy` (host-tested: NV12, NV21, I420, padded rows; negative control). A frame with no pending request is dropped and the pool buffer goes straight back to HAL1. A failed copy fails that one request (`bq_fail`).

- `AHardwareBuffer_createFromHandle` (clone) refused every framework buffer with -22, for any stride or usage tried. The provider has already imported these buffers, so the bridge locks them as they are through the device's gralloc1 module (`bridge_gralloc1.c`; Mali `gralloc.exynos5.so`, module API 1.0, `lock_flex`/`unlock`). The function numbers were taken from AOSP `gralloc1.h` and cross-checked on the phone: `GET_DIMENSIONS` returns 1440x1080 and `GET_FORMAT` `0x11` (NV21) with 3 flex planes for the framework buffer.
- Probe CONTROL trial on camera 2, 1440x1080 YUV: **verdict WORKS, 49 and 46 frames in 2 s** (two runs; `results/sm-n950f/probe_20261114_104558-5518.json`, `probe_20261114_104741-6931.json`), 0 capture failures; the bridge logged copied 49/46, dropped 0, copy failed 0.
- Content: with `persist.instruments.camera.bridge_dump` set, frame 31 was read back from the framework buffer after the copy (NV21 SHA-256 `3AB67D21...B36434B8`, kept outside the repo because it shows the room): a real image of the close indoor wall, mean luma 168.4.
- Not determined for this run: which sensor the fusion stage chose. The scene was close and indoor, where the earlier test saw Samsung fall back to a wide-camera crop; the later daylight run is under "Which sensor at 2x" below.

Cost: one CPU copy per frame, about 2.3 MB at 1440x1080.

### Stall after ~50 frames, fixed by a copier thread (2026-11-14)

Longer trials (new `stream_ms` probe extra, `run_probe.py --stream-ms`) showed the stream stopping after 52 and 75 frames in two 8 s runs: HAL1's buffer manager reported `Failed to get available gralloc buffer from buffer collector` every frame, while the pool trace showed the last dequeue had succeeded and HAL1 simply stopped calling the window. The 2 s runs above ended before this showed. Separating check at the same scene: Samsung's dual mode through hal1probe's window (no copy, no framework calls) ran 8 s at 24.6 fps with no stall. The difference was the bridge doing the copy and the framework result callback on HAL1's enqueue thread. `bridge_window.c` now queues the filled buffer and returns at once; a copier thread copies and delivers. After the change: four 8 s runs, 201/202/201/201 frames (25 fps), no collector errors, 0 failed copies (`results/sm-n950f/probe_20261114_1130*`, `_113220-8d04`).

Gap in the oracle: the trial verdict is WORKS at >= 10 frames regardless of length, so the stalled runs (52 and 75 frames in 8 s) also read WORKS. A rate-based threshold would catch a stall; not changed here.

### Which sensor at 2x: the telephoto, when the scene allows it (2026-11-14)

The second "daylight" attempt (11:2x) had the phone facing the same close indoor wall: the telephoto-only frame was the blurred wall, and ORB found too few features to measure scale between any pair.

Third attempt (14:18-14:19), phone pointed up at the ceiling and a daylit skylight (a few metres away): an 8 s camera 2 trial through the bridge (238 frames copied, 0 dropped, 0 failed; `results/sm-n950f/probe_20261114_141832-4435.json`), copied frame 150 read back from the framework buffer, then hal1probe frames of the telephoto alone (`"3"`) and the wide camera alone (`"0"`) at 1440x1080. Images kept outside the repo (`note8_camera_stack/bridge/day3_*`).

| Pair | Scale | Telephoto hypothesis | Wide 2x crop hypothesis |
|---|---|---|---|
| telephoto vs wide | 1.867 (136/406 inliers) | (lens ratio on these streams) | |
| bridge frame 150 vs telephoto | **1.000** (280/451 inliers) | 1.000 | about 1.07 |
| bridge frame 150 vs wide | **1.885** (68/168 inliers) | 1.867 | about 2.0 |

**Camera 2 through the bridge delivered the telephoto image to an app at 2x.** The phone moved between captures (shift about 470 px), which changes position but not scale. Limits: one frame of one run was checked, so a switch to the wide crop mid-stream (Samsung's lux and distance fallback, as seen in the dim close scene) is still possible and is not flagged by the bridge. For close-range work the fallback is expected to pick the wide crop.

## Telephoto-only mode, now the default (2026-11-14)

Dual mode hands the output to Samsung's fusion stage, which picks a wide-camera crop for dim or close scenes: the wrong choice for microscope work. Camera 2 now opens HAL1 `"3"` (the telephoto alone) by default; `persist.instruments.camera.bridge_mode=dual` restores dual mode. `"3"` rejects standard window buffers (milestone 1), so the bridge sets no window and enables `CAMERA_MSG_PREVIEW_FRAME`: each NV21 callback frame is copied into one of 4 CPU slots on HAL1's thread (the callback memory is freed when it returns) and the existing copier thread copies the slot into the framework buffer (`bridge_tele.c`; packed NV21 is described for `yuv420_copy` by the new host-tested `yuv_describe_nv21`). Shutter timestamps are `CLOCK_BOOTTIME`, matching camera 3's `timestampSource` REALTIME. Cost: two CPU copies per frame.

Device results, phone close to a wall:

- 8 s camera 2 trial: WORKS, 231 frames copied, 5 dropped (no free slot), 0 failed (`results/sm-n950f/probe_20261114_143141-8f3d.json`).
- Which sensor runs, from the kernel log (cleared before the run): in telephoto-only mode only sensor position 2 opens (`REAR_2ND(Tele)`), and position 0 (wide) never starts (`probe_20261114_143451-a71d`). The same check in dual mode opened positions 0 and 2.
- Image: copied frame 150 against hal1probe frames of `"3"` and `"0"` taken right after. ORB found too few features on the blurred wall, so scale was found by normalised cross-correlation (scratch `ncc_scale.py`, checked on the daylight set: 1.87, the same as ORB). Bridge vs telephoto: best scale 0.99 (NCC 0.983); bridge vs wide: 1.89; telephoto vs wide: 1.92.
- Not shown: that dual mode would have cropped the wide camera at this scene. Its frame also measured 0.99 against the telephoto (`probe_20261114_143401-5075`), so this scene does not separate the modes by image. The kernel log does: telephoto-only mode never starts the wide sensor, so its output cannot be a wide crop.

## Surviving reboots (2026-11-14)

`tools/camshim/note8_telephoto.py persist` installs one init script, `/system/etc/init/instruments_camshim.rc`, that bind-mounts `/data/local/tmp/instruments/camera.universal8895.so` over the camera HAL `on post-fs-data`. The camera provider is `class hal`, started `on boot`, so the mount is in place first. `/` is plain ext4 on this build (`/dev/block/sda15`, no dm-verity device), so the one-time remount turns off no verification. `unpersist` deletes the script. A ROM update replaces `/system` and removes it.

Verified: after `adb reboot` (boot completed in about 32 s), with adb back to non-root, `/proc/mounts` showed the bind mount, the camera service listed 3 devices, and the probe app's camera 2 trial was WORKS with 232 frames in 8 s through `open_legacy("3")` (`probe_20261114_143841-bc75`).

## Thresholds

As in `device-probe.md`: a trial WORKS at >= 10 frames per stream in 2 s.
