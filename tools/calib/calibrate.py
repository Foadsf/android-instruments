"""Calibrate cameras 0 and 2 from a capture series (docs/units/camera-calibration.md).

    python tools/calib/calibrate.py <bursts>/<run_id>_series [--board-mm 200.0,160.0]
        [--displacement 3,4,100] [--ncc-pose 0] [--device sm-n950f]

The series folder is written by the microscope app (run mode `series`, `run_live.py --series`):
series.json plus pose_NN/cam<id>/frame_NN.yuv bursts. Writes
results/<device>/camera_calibration_<date>_<run_id>.json. Exit codes: 0 pass, 1 fail,
2 usage, 3 cannot judge (fewer than 8 usable views on a camera).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import calib_core as cc  # noqa: E402
from make_target import board_object  # noqa: E402

SPEC = HERE / "target_a4_v2_landscape.json"
HELDOUT_RMS = {"0": 0.5, "2": 0.8}
HALVES_FX_REL, HALVES_C_PX = 0.005, 3.0
DISPLACEMENT_TOL_MM = 1.5
STRAIGHT_RMS_PX = 0.15  # amended for the streaked print (was max 0.3 px), before any device run
NCC_REL = 0.01
MIN_CORNER_FRACTION = 0.6
STEREO_T_MM, STEREO_R_DEG = (5.0, 20.0), 3.0
FOCUS_TOL_D = 0.05
CLOCK_LAG_MS = (0, 1000)
DUP_PX = 30.0  # hand-held amendment: about 1.5 deg of turn on camera 0, 0.8 deg on camera 2


def check(name, ok, value, threshold, judged=True):
    return {"check": name, "ok": bool(ok) if judged else True, "judged": judged, "value": value, "threshold": threshold}


def mean_luma(burst: Path):
    meta = json.loads((burst / "burst.json").read_text())
    w, h = meta["width"], meta["height"]
    frames = [np.fromfile(f, np.uint8)[: w * h].reshape(h, w).astype(np.float64) for f in sorted(burst.glob("frame_*.yuv"))]
    if not frames:
        raise ValueError(f"{burst}: no frames")
    return np.round(np.mean(frames, axis=0)).astype(np.uint8), (w, h)


def near_duplicate(view: dict, kept: list) -> int | None:
    """The pose of a kept view this one barely differs from (most corners shared, every shared
    corner within DUP_PX), or None. A slow hand-held sweep can keep two frames of almost one view;
    both in the fit, or one held out, would make the held-out and halves checks look better than
    the views deserve. The largest shift, not the median: a 20 deg turn about the board centre
    moves the median corner under 30 px but the board's edge by 50 px."""
    for k in kept:
        common, ia, ib = np.intersect1d(view["ids"], k["ids"], return_indices=True)
        if len(common) >= 0.8 * min(len(view["ids"]), len(k["ids"])) and \
                float(np.linalg.norm(view["img"][ia] - k["img"][ib], axis=1).max()) < DUP_PX:
            return k["pose"]
    return None


def collect(root: Path, series: dict, board, scale_xy) -> tuple[dict, list, dict]:
    """Per camera: usable views; plus the dropped list and each pose's mean frame per camera."""
    hand_held = series.get("capture") == "hand-held sweep"
    views: dict[str, list] = {c: [] for c in series["cameras"]}
    dropped, frames = [], {}
    for p in series["poses"]:
        if p.get("status") != "ok":
            dropped.append({"pose": p["index"], "camera": "all", "reason": p.get("status", "unknown")})
            continue
        for cam, rel in p.get("bursts", {}).items():
            # Camera 0 only: the bridged camera 2 echoes the requested focus without applying it.
            want, got = series.get("focus_diopters"), p.get("cameras", {}).get(cam, {}).get("focus_diopters")
            if cam == "0" and want is not None and (got is None or abs(got - want) > FOCUS_TOL_D):
                dropped.append({"pose": p["index"], "camera": cam, "reason": f"focus {got} D, requested {want} D"})
                continue
            img, size = mean_luma(root / rel)
            frames[(p["index"], cam)] = img
            corners, ids = cc.detect_corners(img, board)
            n = 0 if ids is None else len(ids)
            if n < cc.MIN_CORNERS:
                dropped.append({"pose": p["index"], "camera": cam, "reason": f"{n} corners"})
                continue
            view = {"pose": p["index"], "obj": cc.object_points(board, ids, scale_xy), "img": corners, "ids": ids,
                    "size": size}
            twin = near_duplicate(view, views[cam]) if hand_held else None
            if twin is not None:
                dropped.append({"pose": p["index"], "camera": cam, "reason": f"near-duplicate of pose {twin}"})
                continue
            views[cam].append(view)
    return views, dropped, frames


def visible_fraction(view, cal, board, scale_xy) -> float:
    import cv2
    all_ids = np.arange(len(board.getChessboardCorners()))
    rv, tv = cc.solve_pose(view, cal["K"], cal["dist"])
    proj, _ = cv2.projectPoints(cc.object_points(board, all_ids, scale_xy).astype(np.float32), rv, tv, cal["K"], cal["dist"])
    w, h = view["size"]
    p = proj.reshape(-1, 2)
    visible = int(((p[:, 0] >= 0) & (p[:, 1] >= 0) & (p[:, 0] < w) & (p[:, 1] < h)).sum())
    return len(view["ids"]) / visible if visible else 0.0


def camera_report(cam: str, views: list, board, scale_xy, cols: int) -> dict:
    train, ev = cc.split_views(len(views))
    size = views[0]["size"]
    cal = cc.calibrate([views[i] for i in train], size)
    a, b = cc.halves(len(train))
    ca = cc.calibrate([views[train[i]] for i in a], size)
    cb = cc.calibrate([views[train[i]] for i in b], size)
    k, d = cal["K"], cal["dist"]
    held = cc.reprojection_rms([views[i] for i in ev], k, d)
    ids = [v["ids"] for v in views]
    straight, straight_max = cc.straightness(views, ids, k, d, cols), cc.straightness(views, ids, k, d, cols, "max")
    poses = {}
    for v in views:
        rv, tv = cc.solve_pose(v, k, d)
        dist_mm, tilt = cc.wall_distance_tilt(rv, tv)
        poses[v["pose"]] = {"distance_mm": round(dist_mm, 2), "tilt_deg": round(tilt, 2),
                            "mm_per_px": round(dist_mm / k[0, 0], 5), "corners": len(v["ids"]),
                            "corner_fraction": round(visible_fraction(v, cal, board, scale_xy), 3)}
    fx_rel = abs(ca["K"][0, 0] - cb["K"][0, 0]) / cal["K"][0, 0]
    c_px = max(abs(ca["K"][0, 2] - cb["K"][0, 2]), abs(ca["K"][1, 2] - cb["K"][1, 2]))
    fractions = [p["corner_fraction"] for p in poses.values()]
    checks = [
        check("held-out reprojection RMS (px)", held <= HELDOUT_RMS[cam], round(held, 3), HELDOUT_RMS[cam]),
        check("halves agree: fx (relative)", fx_rel <= HALVES_FX_REL, round(fx_rel, 5), HALVES_FX_REL),
        check("halves agree: cx, cy (px)", c_px <= HALVES_C_PX, round(c_px, 2), HALVES_C_PX),
        check("straightness after undistortion, RMS (px)", straight <= STRAIGHT_RMS_PX, round(straight, 3),
              STRAIGHT_RMS_PX),
        check("straightness after undistortion, max (px)", True, round(straight_max, 3), "recorded", judged=False),
        check("median corner fraction per view", float(np.median(fractions)) >= MIN_CORNER_FRACTION,
              round(float(np.median(fractions)), 3), MIN_CORNER_FRACTION, judged=(cam == "0")),
        check("image coverage by corners (8 x 6 cells)", True, round(cc.coverage(views, size), 3), "recorded",
              judged=False),
    ]
    return {"views": len(views), "train": [views[i]["pose"] for i in train], "eval": [views[i]["pose"] for i in ev],
            "fx": k[0, 0], "fy": k[1, 1], "cx": k[0, 2], "cy": k[1, 2], "dist": d.tolist(), "std": cal["std"],
            "fit_rms": cal["rms"], "poses": poses, "checks": checks, "_cal": cal}


def stereo_report(views: dict, cals: dict) -> dict:
    import cv2
    by_pose = {c: {v["pose"]: v for v in views[c]} for c in ("0", "2")}
    obj, i0, i2 = [], [], []
    for p in sorted(set(by_pose["0"]) & set(by_pose["2"])):
        v0, v2 = by_pose["0"][p], by_pose["2"][p]
        common = np.intersect1d(v0["ids"], v2["ids"])
        if len(common) < cc.MIN_CORNERS:
            continue
        m0, m2 = np.isin(v0["ids"], common), np.isin(v2["ids"], common)
        obj.append(v0["obj"][m0].astype(np.float32))
        i0.append(v0["img"][m0].astype(np.float32))
        i2.append(v2["img"][m2].astype(np.float32))
    if len(obj) < 3:
        return {"pairs": len(obj), "checks": [check("stereo pairs", False, len(obj), ">= 3", judged=False)]}
    c0, c2 = cals["0"], cals["2"]
    rms, *_, r, t, _, _ = cv2.stereoCalibrate(obj, i0, i2, c0["K"], c0["dist"], c2["K"], c2["dist"],
                                              views["0"][0]["size"], flags=cv2.CALIB_FIX_INTRINSIC)
    tn = float(np.linalg.norm(t))
    ang = math.degrees(math.acos(min(1.0, (np.trace(r) - 1) / 2)))
    ok = STEREO_T_MM[0] <= tn <= STEREO_T_MM[1] and ang < STEREO_R_DEG
    return {"pairs": len(obj), "rms": rms, "R": r.tolist(), "T_mm": np.ravel(t).tolist(),
            "checks": [check("pair translation 5-20 mm and rotation < 3 deg (sanity)", ok,
                             {"T_mm": round(tn, 2), "R_deg": round(ang, 3)}, "recorded", judged=False)]}


def displacement_checks(reports: dict, spec: tuple[int, int, float] | None) -> list[dict]:
    if spec is None:
        return [check("known displacement", False, "not captured", "--displacement A,B,MM", judged=False)]
    a, b, mm = spec
    out = []
    for cam, rep in reports.items():
        pa, pb = rep["poses"].get(a), rep["poses"].get(b)
        if pa is None or pb is None:
            out.append(check(f"camera {cam}: known {mm:g} mm displacement", False, "pose not usable", mm))
            continue
        delta = abs(pb["distance_mm"] - pa["distance_mm"])
        out.append(check(f"camera {cam}: known {mm:g} mm displacement (computed mm)",
                         abs(delta - mm) <= DISPLACEMENT_TOL_MM, round(delta, 2), f"{mm:g} +- {DISPLACEMENT_TOL_MM}"))
    return out


def ratio_checks(reports: dict, frames: dict, pose: int | None) -> list[dict]:
    if not {"0", "2"} <= set(reports):
        return []
    fx_ratio = reports["2"]["fx"] / reports["0"]["fx"]
    poses = [p for p in reports["0"]["poses"] if p in reports["2"]["poses"]]
    pose = pose if pose is not None else (poses[0] if poses else None)
    if pose is None or (pose, "0") not in frames or (pose, "2") not in frames:
        return [check("fx2/fx0 vs NCC", False, {"fx_ratio": round(fx_ratio, 4)}, "no common pose", judged=False)]
    s, ncc = cc.ncc_ratio(frames[(pose, "0")], frames[(pose, "2")], reports["0"]["_cal"], reports["2"]["_cal"])
    rel = abs(fx_ratio - s) / s
    return [check("fx2/fx0 vs NCC scale on the same undistorted pose (relative)", rel <= NCC_REL,
                  {"fx_ratio": round(fx_ratio, 4), "ncc_scale": round(s, 4), "ncc": round(ncc, 3), "pose": pose,
                   "rel": round(rel, 4)}, NCC_REL)]


def imu_report(series: dict, views0: list, cal0: dict) -> dict:
    import cv2
    by_pose = {p["index"]: p for p in series["poses"]}
    up, board_up = [], []
    for v in views0:
        acc = by_pose[v["pose"]].get("accel_mean")
        if not acc:
            continue
        rv, _ = cc.solve_pose(v, cal0["K"], cal0["dist"])
        r, _ = cv2.Rodrigues(rv)
        up.append(cc.device_to_camera(acc))
        board_up.append(-r[:, 1])
    if len(up) < 3:
        return {"poses": len(up), "checks": []}
    rot, res = cc.imu_rotation(np.array(up), np.array(board_up))
    ang = math.degrees(math.acos(min(1.0, (np.trace(rot) - 1) / 2)))
    return {"poses": len(up), "rotation": rot.tolist(), "rotation_deg": round(ang, 3), "residual_rms_deg": round(res, 3),
            "checks": [check("IMU-to-camera residual after the fitted rotation (deg)", True, round(res, 3), "recorded",
                             judged=False)]}


def clock_checks(series: dict) -> list[dict]:
    """Hand-held sweep: the gyro gate compares frame and gyro timestamps, so they must share one
    clock. A frame reaches the app after its exposure: the arrival lag must be positive and short."""
    out = []
    for cam, s in series.get("per_camera", {}).items():
        lag = (s.get("arrival_lag_ms") or {}).get("median")
        ok = lag is not None and CLOCK_LAG_MS[0] < lag < CLOCK_LAG_MS[1]
        out.append(check(f"camera {cam}: frame clock is the gyro clock (median arrival lag, ms)", ok,
                         None if lag is None else round(lag, 1), f"{CLOCK_LAG_MS[0]}..{CLOCK_LAG_MS[1]}"))
    return out


def evaluate(root: Path, args) -> tuple[dict, int]:
    series = json.loads((root / "series.json").read_text())
    if args.cameras:  # judge only these (e.g. a run stopped before camera 2); recorded in the report
        series["cameras"] = [c for c in series["cameras"] if c in args.cameras.split(",")]
    spec = json.loads(Path(args.spec).read_text())
    b = spec["board"]
    drawn = (b["cols"] * b["square_mm"], b["rows"] * b["square_mm"])
    measured = tuple(float(v) for v in args.board_mm.split(",")) if args.board_mm else drawn
    scale_xy = (measured[0] / drawn[0], measured[1] / drawn[1])
    board = board_object(b)
    views, dropped, frames = collect(root, series, board, scale_xy)
    report = {"unit": "camera_calibration", "run_id": series.get("run_id"), "series": root.name,
              "target": spec.get("name", Path(args.spec).stem),
              "board_mm_drawn": list(drawn), "board_mm_measured": list(measured),
              "focus_diopters": series.get("focus_diopters"), "cameras_judged": series["cameras"],
              "dropped": dropped, "cameras": {}}
    short = [c for c, v in views.items() if len(v) < cc.MIN_VIEWS]
    if short:
        report["verdict"] = "cannot judge"
        report["reason"] = {c: f"{len(views[c])} usable views, need {cc.MIN_VIEWS}" for c in short}
        return report, 3
    reps = {c: camera_report(c, v, board, scale_xy, b["cols"]) for c, v in views.items()}
    disp = tuple(float(x) for x in args.displacement.split(",")) if args.displacement else None
    disp = (int(disp[0]), int(disp[1]), disp[2]) if disp else None
    report["pair_checks"] = displacement_checks(reps, disp) + ratio_checks(reps, frames, args.ncc_pose)
    if series.get("capture") == "hand-held sweep":
        report["pair_checks"] += clock_checks(series)
        report["hand_held_note"] = ("one camera at a time while moving: no pose is shared by both cameras, so the "
                                    "pair, the known displacement and the NCC ratio are recorded as not captured")
    if {"0", "2"} <= set(reps):
        report["stereo"] = stereo_report(views, {c: r["_cal"] for c, r in reps.items()})
    if "0" in reps:
        report["imu"] = imu_report(series, views["0"], reps["0"]["_cal"])
    for c, r in reps.items():
        r.pop("_cal")
        report["cameras"][c] = r
    allc = [x for r in reps.values() for x in r["checks"]] + report["pair_checks"]
    report["verdict"] = "pass" if all(x["ok"] for x in allc) else "fail"
    return report, 0 if report["verdict"] == "pass" else 1


def device_of(run_id: str) -> str:
    """The results/<device> folder of the run report that produced this series."""
    for p in sorted((REPO / "results").glob(f"*/microscope_*_{run_id}.json")):
        return p.parent.name
    return "unknown"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("series", type=Path)
    ap.add_argument("--spec", default=str(SPEC), help="target spec JSON (default: the printed A4 v2 target)")
    ap.add_argument("--board-mm", help="measured board width,height in mm (default: the drawn size)")
    ap.add_argument("--displacement", help="A,B,MM: poses A and B were MM apart along the wall normal")
    ap.add_argument("--ncc-pose", type=int)
    ap.add_argument("--cameras", help="comma-separated: judge only these cameras of the series")
    ap.add_argument("--device", default=None, help="results/<device> folder (default: from the run report)")
    ap.add_argument("--out", type=Path, help="report path (default under results/)")
    args = ap.parse_args(argv)
    if not (args.series / "series.json").is_file():
        print(f"no series.json in {args.series}", file=sys.stderr)
        return 2
    try:
        report, code = evaluate(args.series, args)
    except (ValueError, OSError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    device = args.device or device_of(str(report.get("run_id")))
    out = args.out or (REPO / "results" / device / f"camera_calibration_{dt.date.today():%Y%m%d}_{report.get('run_id')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=float) + "\n")
    print(json.dumps({"verdict": report["verdict"], "file": str(out)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
