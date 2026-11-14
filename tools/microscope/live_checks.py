"""Checks for the microscope-live run report (docs/units/microscope-live.md), host side.

The thresholds are the ones the contract declared before the first run. The sharpness cross-check
recomputes the app's focus measure from the raw burst with NumPy, written independently of the
Kotlin code, so a wrong Laplacian or a wrong ROI on either side shows up as a disagreement.
"""
from __future__ import annotations

from pathlib import Path

MIN_FPS = 20.0
FPS_CAMERA = "2"
MAX_GAP_PERIODS = 2.0
SHARPNESS_REL_TOL = 0.01


def check(name: str, ok: bool, value, threshold) -> dict:
    return {"check": name, "ok": bool(ok), "value": value, "threshold": threshold}


def timestamp_checks(ts: list[int], fps: float) -> list[dict]:
    increasing = all(b > a for a, b in zip(ts, ts[1:]))
    out = [check("timestamps strictly increasing", increasing, increasing, True)]
    if len(ts) >= 2 and fps > 0:
        period = 1e9 / fps
        worst = max(b - a for a, b in zip(ts, ts[1:])) / period
        out.append(check("largest gap in frame periods", worst <= MAX_GAP_PERIODS, round(worst, 2), MAX_GAP_PERIODS))
    return out


def camera_checks(cam: dict, burst_frames: int, stream_fps: float | None = None) -> list[dict]:
    """All checks for one camera entry of the report. A camera that errored fails. The frame-rate
    threshold was declared for camera 2 (the telephoto through the bridge); for other cameras, as in
    pair mode, the rate is recorded but not judged."""
    if "error" in cam:
        return [check("camera opened and streamed", False, cam["error"], "no error")]
    s = cam.get("stream", {})
    fps = s.get("fps", 0.0)
    judged = str(cam.get("camera_id")) == FPS_CAMERA
    out = [
        check("stream fps", fps >= MIN_FPS, round(fps, 2), f">= {MIN_FPS}") if judged
        else check("stream fps (recorded, no threshold)", True, round(fps, 2), None),
        check("capture failures", s.get("capture_failures", -1) == 0, s.get("capture_failures"), 0),
    ]
    b = cam.get("burst", {})
    out.append(check("burst frames saved", b.get("frames") == burst_frames and b.get("complete") is True,
                     b.get("frames"), burst_frames))
    out += timestamp_checks(b.get("timestamps_ns", []), stream_fps or fps)
    return out


def verdict(report: dict) -> dict:
    cams = report.get("cameras", [])
    per = {str(c.get("camera_id")): camera_checks(c, report.get("burst_frames", 0)) for c in cams}
    ok = bool(per) and all(c["ok"] for checks in per.values() for c in checks)
    return {"verdict": "pass" if ok else "fail", "cameras": per}


# ---- NumPy cross-check of the sharpness score -------------------------------------------------

def read_luma(path: Path, w: int, h: int):
    import numpy as np
    data = np.fromfile(path, dtype=np.uint8)
    if data.size != w * h * 3 // 2:
        raise ValueError(f"{path}: {data.size} bytes, expected {w * h * 3 // 2} for I420 {w}x{h}")
    return data[: w * h].reshape(h, w)


def sharpness_np(luma) -> float:
    """Mean squared 4-neighbour Laplacian over the interior of the centre-half ROI."""
    import numpy as np
    h, w = luma.shape
    roi = luma[h // 4: h // 4 + h // 2, w // 4: w // 4 + w // 2].astype(np.int64)
    lap = 4 * roi[1:-1, 1:-1] - roi[1:-1, :-2] - roi[1:-1, 2:] - roi[:-2, 1:-1] - roi[2:, 1:-1]
    return float((lap * lap).mean())


def sharpness_crosscheck(burst_dir: Path, burst: dict) -> dict:
    app = burst.get("sharpness_frame0")
    host = sharpness_np(read_luma(burst_dir / "frame_00.yuv", burst["width"], burst["height"]))
    rel = abs(host - app) / host if host and app is not None else float("inf")
    return check("sharpness app vs NumPy (relative)", rel <= SHARPNESS_REL_TOL,
                 {"app": app, "numpy": round(host, 3), "rel": rel}, SHARPNESS_REL_TOL)
