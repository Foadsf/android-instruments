# Unit: camera shim (expose uncounted vendor cameras)

- **Stage:** 1 (device facts), needed before any telephoto work on the Note8
- **Paths:** `core/camera_idmap` (pure ID map), `android/camshim` (shim), `android/halprobe` (HAL probe), `tools/camshim/note8_telephoto.py` (install/revert)
- **Replaces at run time:** LineageOS's pass-through "Zero Camera Wrapper" (`/system/lib/hw/camera.universal8895.so`, source: github.com/8890q/android_device_samsung_universal8895-common, `hardware/camera/`). Its only behaviours besides pass-through, loading `camera.vendor` and disabling fdsan, are kept.

## Why

On the Note8 (SM-N950F, LineageOS 20) apps see two cameras. `halprobe` showed on 2026-11-14 that Samsung's HAL counts 2 but answers `get_camera_info` for more IDs: 0 (wide), 1 and 2 (front), **3 (telephoto: back, 4.2 mm, 3.2 x 2.4 mm sensor, 4032x3024; reads `rear2_sensorid`, sensor 33)**, 20 (wide alias) and 50 (telephoto alias); all others return -19.

## Contract

- **Input:** the vendor module (via `hw_get_module_by_class("camera", "vendor")`) and `persist.instruments.camera.extra_ids` (default `3`).
- **Output:** a `camera_module_t` reporting `vendor_count + n_extra` cameras; framework IDs `0..vendor_count-1` pass through, `vendor_count + k` maps to extra ID k; vendor aliases not listed stay hidden. An extra ID is kept only if the vendor `get_camera_info` answers for it.

## Oracle and thresholds

| Check | Threshold | Where |
|---|---|---|
| ID map (host) | Note8 map: 3 cameras, framework 2 <-> vendor 3, vendor 2/20/50 hidden | `core/camera_idmap/tests` + negative control |
| Shim loaded by `halprobe32` as shell (no root) | count 3; camera 2 = back, 4.2 mm, 3.2 x 2.4 mm; camera 3 rejected | `results/sm-n950f/halprobe32_shim_20261114.json` (passed) |
| Installed (root) | `dumpsys media.camera` lists 3 devices; probe app sees camera 2 with focal length 4.2 and a `CONTROL` trial that WORKS | `tools/camshim/note8_telephoto.py status`, `tools/probe/run_probe.py` |

## Install and revert

Needs adb as root (Developer options -> Rooted debugging). The shim is bind-mounted from `/data/local/tmp`, nothing on `/system` changes, dm-verity is untouched, and a reboot reverts it.

```bash
pwsh android/camshim/build.ps1
python tools/camshim/note8_telephoto.py install
python tools/camshim/note8_telephoto.py revert
```

## Results of the installed run (2026-11-14)

- Exposure works: the camera service and an ordinary app see camera 2 = telephoto. LineageOS's aux-camera filter did not hide it.
- Streaming does not: opened alone, the telephoto delivers no frames, and a second solo attempt panicked the kernel in the ISP driver. See `results/README.md`.

## Next experiment (needs Foad's go-ahead: it can panic the phone again)

Open camera 0 and camera 2 at the same time (`CONCURRENT_PAIR` trial, already in the probe app). If the telephoto streams only while the wide camera runs, the HAL treats it as the dual-mode follower, and the shim must keep the wide pipeline running underneath it. If that also fails or panics, telephoto streaming on this ROM needs Samsung's dual-mode entry points (`HAL_camera_device_dual_*`), which means reverse engineering, not configuration.
