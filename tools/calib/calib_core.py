"""Camera calibration from ChArUco views (docs/units/camera-calibration.md): detection,
calibration, and the checks that do not come from the fit itself.

Corner detection re-refines OpenCV's ChArUco corners with cornerSubPix: on the independent
synthetic renderer (synth_camera.py) OpenCV 4.13's CharucoDetector returned every corner
+0.5 px off in x and y; one cornerSubPix pass brings the mean error to 0.00 px.
"""
from __future__ import annotations

import math

import numpy as np

MIN_CORNERS = 12
MIN_VIEWS = 8
EVAL_EVERY = 4  # every 4th usable view is held out of the fit


def detect_corners(img, board, destreak: bool = True):
    """(corners N x 2 float, ids N int) in pixel-centre-at-integer coordinates, or (None, None).

    destreak: find markers and corners on a 5 x 5 median of the frame, which removes the thin
    bright nozzle streaks of the 2026-11-14 print (they split marker borders: 21 of 63 corners on
    the real frame, 63 of 63 after the median), then refine on the original frame: refining on
    the median adds 0.1 px RMS error on the synthetic streaked renders, refining on the original
    stays unbiased (camera-calibration.md, amendment for the existing print). With destreak the
    detector also widens the adaptive threshold window to 43 px (camera 2's markers are ~110 px),
    re-finds missed markers, and accepts a corner next to a single marker: on the real camera 2
    frames 15 -> 54 corners, camera 0 57 -> 63; positions still come from cornerSubPix."""
    import cv2
    det = cv2.aruco.CharucoDetector(board)
    found = img
    if destreak:
        found = cv2.medianBlur(img, 5)
        dp = cv2.aruco.DetectorParameters()
        dp.adaptiveThreshWinSizeMax = 43
        cp = cv2.aruco.CharucoParameters()
        cp.tryRefineMarkers, cp.minMarkers = True, 1
        det.setDetectorParameters(dp)
        det.setCharucoParameters(cp)
    corners, ids, _, _ = det.detectBoard(found)
    if ids is None or len(ids) == 0:
        return None, None
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4)
    refined = cv2.cornerSubPix(img, corners.astype(np.float32).copy(), (5, 5), (-1, -1), crit)
    return refined.reshape(-1, 2).astype(np.float64), ids.ravel().astype(int)


def object_points(board, ids, scale_xy=(1.0, 1.0)):
    """Board corners in mm for the given ids, scaled per axis by measured / drawn size."""
    p = board.getChessboardCorners()[ids].astype(np.float64)
    p[:, 0] *= scale_xy[0]
    p[:, 1] *= scale_xy[1]
    return p


def split_views(n: int) -> tuple[list[int], list[int]]:
    ev = [i for i in range(n) if i % EVAL_EVERY == EVAL_EVERY - 1]
    return [i for i in range(n) if i not in ev], ev


def calibrate(views: list[dict], size, fix_distortion: bool = False, fix_k3: bool = True) -> dict:
    """views: [{'obj': N x 3, 'img': N x 2}]. k1, k2, p1, p2 with k3 = 0 by default: on the
    synthetic camera the free k3 came out 1.56 +- 0.69 (truth 0), dragging k1 off by 3 sigma and
    the distortion field off by 374 px in the uncovered image corners (contract amendment)."""
    import cv2
    flags = cv2.CALIB_FIX_K3 if fix_k3 else 0
    if fix_distortion:
        flags = cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3 | cv2.CALIB_ZERO_TANGENT_DIST
    obj = [v["obj"].astype(np.float32) for v in views]
    img = [v["img"].astype(np.float32) for v in views]
    rms, k, d, rv, tv, std_in, _, per_view = cv2.calibrateCameraExtended(obj, img, tuple(size), None, None, flags=flags)
    std = std_in.ravel()
    return {"rms": float(rms), "K": k, "dist": d.ravel()[:5], "rvecs": rv, "tvecs": tv,
            "per_view_rms": per_view.ravel().tolist(),
            "std": {"fx": float(std[0]), "fy": float(std[1]), "cx": float(std[2]), "cy": float(std[3]),
                    "k1": float(std[4]), "k2": float(std[5]), "p1": float(std[6]), "p2": float(std[7]),
                    "k3": float(std[8])}}


def coverage(views: list[dict], size, grid=(8, 6)) -> float:
    """Fraction of image cells (8 x 6 grid) holding at least one detected corner, over all views:
    the distortion model is only trusted where the data reached."""
    w, h = size
    hit = np.zeros(grid[::-1], bool)
    for v in views:
        cx = np.clip((v["img"][:, 0] / w * grid[0]).astype(int), 0, grid[0] - 1)
        cy = np.clip((v["img"][:, 1] / h * grid[1]).astype(int), 0, grid[1] - 1)
        hit[cy, cx] = True
    return float(hit.mean())


def solve_pose(view: dict, k, dist):
    import cv2
    ok, rv, tv = cv2.solvePnP(view["obj"].astype(np.float32), view["img"].astype(np.float32), k, dist)
    return rv, tv


def reprojection_rms(views: list[dict], k, dist) -> float:
    import cv2
    sq, n = 0.0, 0
    for v in views:
        rv, tv = solve_pose(v, k, dist)
        proj, _ = cv2.projectPoints(v["obj"].astype(np.float32), rv, tv, k, dist)
        sq += float(((proj.reshape(-1, 2) - v["img"]) ** 2).sum())
        n += len(v["img"])
    return math.sqrt(sq / n) if n else float("inf")


def halves(n_views: int, a: list[int] | None = None, b: list[int] | None = None):
    """Two disjoint halves of the training views (even / odd); refuses overlapping sets."""
    a = list(range(0, n_views, 2)) if a is None else a
    b = list(range(1, n_views, 2)) if b is None else b
    if set(a) & set(b):
        raise ValueError("halves overlap: shared views make their agreement meaningless")
    return a, b


def straightness(views: list[dict], ids_list: list, k, dist, cols: int, stat: str = "rms") -> float:
    """Distance (px) of undistorted corners from their row or column line (total least squares),
    over all views: RMS (judged) or max (recorded); rows and columns with fewer than 3 corners
    are skipped. The RMS, not the max, is judged since the streaked print: its corner noise put
    the max at 0.52 px with the right model, while the RMS separates 0.087 px (right model) from
    0.21 px (distortion ignored) on the synthetic streaked renders."""
    import cv2
    devs = []
    for v, ids in zip(views, ids_list):
        und = cv2.undistortPoints(v["img"].reshape(-1, 1, 2).astype(np.float64), k, dist, P=k).reshape(-1, 2)
        for key in (ids // (cols - 1), ids % (cols - 1)):
            for g in np.unique(key):
                pts = und[key == g]
                if len(pts) < 3:
                    continue
                c = pts - pts.mean(0)
                normal = np.linalg.svd(c)[2][1]
                devs.extend(np.abs(c @ normal).tolist())
    if not devs:
        return float("inf")
    d = np.asarray(devs)
    return float(np.sqrt(np.mean(d ** 2))) if stat == "rms" else float(d.max())


def wall_distance_tilt(rvec, tvec) -> tuple[float, float]:
    """Distance (mm) from the camera centre to the board plane, and the angle (deg) between the
    optical axis and the board normal."""
    import cv2
    r, _ = cv2.Rodrigues(rvec)
    n = r[:, 2]
    return abs(float(n @ np.ravel(tvec))), math.degrees(math.acos(min(1.0, abs(float(n[2])))))


def ncc_ratio(img0, img2, cal0: dict, cal2: dict, lo=1.5, hi=2.3) -> tuple[float, float]:
    """Telephoto-to-wide scale by NCC on undistorted frames of one pose (tools/microscope
    ncc_scale.score), coarse 0.01 then fine 0.001 steps with a parabolic peak."""
    import sys
    from pathlib import Path

    import cv2
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "microscope"))
    from ncc_scale import score

    def prep(img, cal):
        u = cv2.undistort(img, cal["K"], cal["dist"])
        return cv2.resize(u, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA).astype(np.float32)

    a, b = prep(img0, cal0), prep(img2, cal2)
    coarse = max((score(a, b, s), s) for s in np.arange(lo, hi + 1e-9, 0.01))[1]
    fine = np.arange(coarse - 0.015, coarse + 0.0151, 0.001)
    sc = np.array([score(a, b, s) for s in fine])
    i = int(np.argmax(sc))
    if 0 < i < len(sc) - 1:
        den = sc[i - 1] - 2 * sc[i] + sc[i + 1]
        off = 0.5 * (sc[i - 1] - sc[i + 1]) / den if den != 0 else 0.0
        return float(fine[i] + off * 0.001), float(sc[i])
    return float(fine[i]), float(sc[i])


def device_to_camera(a_dev) -> np.ndarray:
    """Nominal device axes to camera axes (back camera, seen upright with the phone's right edge
    up, 2026-11-14): x_img = -y_dev, y_img = -x_dev, z_cam = -z_dev."""
    a = np.asarray(a_dev, float)
    return np.array([-a[1], -a[0], -a[2]])


def imu_rotation(up_cam: np.ndarray, board_up: np.ndarray) -> tuple[np.ndarray, float]:
    """Rotation R minimising the angle between R @ up_cam[i] and board_up[i] (Kabsch on unit
    vectors), and the RMS residual angle in degrees after it."""
    u = up_cam / np.linalg.norm(up_cam, axis=1, keepdims=True)
    b = board_up / np.linalg.norm(board_up, axis=1, keepdims=True)
    h = u.T @ b
    uu, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ uu.T))
    r = vt.T @ np.diag([1, 1, d]) @ uu.T
    res = np.degrees(np.arccos(np.clip(np.sum((u @ r.T) * b, axis=1), -1, 1)))
    return r, float(np.sqrt(np.mean(res ** 2)))
