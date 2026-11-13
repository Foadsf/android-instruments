# Unit: device probe

- **Stage:** 1
- **Path:** `android/probe`, `tools/probe`
- **Ported from:** parallax `DeviceProbe.kt` (getprop, root hint, GL renderer) at a1bc267; the rest is new.

## Question it answers

Before any algorithm: what does this exact phone expose to an ordinary app? Camera IDs (listed and hidden), every public characteristic of each, whether the factory lens pose and calibration are populated, whether two physical cameras can stream in one session, and which compute paths the phone advertises.

## Contract

- **Input:** a phone over adb. `tools/probe/run_probe.py` installs the app, grants CAMERA and starts it with a run id.
- **Output:** `results/<model>/probe_<date>_<run>.json` (schema `instruments.probe/1`), the event log `events_<...>.jsonl`, the raw `dumpsys_media_camera_<...>.txt` and `crosscheck_<...>.json`.

Value conventions in the report: key names are the framework's (`android.lens.facing`); Size and SizeF are `[w, h]`; Rect is `[left, top, width, height]`, as dumpsys prints active arrays; Range is `[lower, upper]`; Rational is `[num, den]`; enums stay integers.

## Camera scan

The listed IDs, every numeric ID 0 to 127, and every physical ID a logical camera names. An ID is recorded when `getCameraCharacteristics` succeeds, with `listed: false` when the framework did not list it.

## Stream trials

| Kind | What it proves |
|---|---|
| `CONTROL` | One stream on a camera ID itself. The positive control: the trial machinery and the camera work. |
| `PHYSICAL_SINGLE` | One stream routed to one physical camera of a logical camera. |
| `PHYSICAL_PAIR` | Two streams routed to two physical cameras in one session: the Gate 1 question. |

Sizes per trial: the largest 4:3 size within 1440x1080, 1920x1080, and the largest common size. For each trial both the `isSessionConfigurationSupported` answer and the real outcome are recorded; frames are counted per stream for 2 s.

## Thresholds (declared before the first run)

| Check | Threshold |
|---|---|
| A trial `WORKS` | session configured and at least 10 frames on every stream in 2 s (5 fps) |
| `dual_physical_streams = yes` | any `PHYSICAL_PAIR` works |
| `= no` | pairs tried, none works, and the same logical camera's `CONTROL` works |
| `= cannot_tell` | the control failed, or no pair could be tried |
| `= not_applicable` | the phone exposes no logical multi-camera |
| Gate 1 cross-check | at least 3 fields agree with dumpsys and none disagrees (`tools/probe/crosscheck.py`) |

## Negative controls

`tools/probe/test_probe_tools.py` changes one field at a time (focus distance, facing, pose presence, physical IDs) against the real Note8 dump; each must turn the cross-check to `fail`. A probe with no camera in common with dumpsys must give `could_not_tell`, never `pass`.

## Device evidence

See `results/README.md`.
