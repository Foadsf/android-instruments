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

## Thresholds

As in `device-probe.md`: a trial WORKS at >= 10 frames per stream in 2 s.
