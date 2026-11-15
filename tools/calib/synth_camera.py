"""Independent synthetic camera for the calibration tests (docs/units/camera-calibration.md).

Renders the printed target through a known pinhole camera with the five-coefficient
radial/tangential distortion model, by per-pixel inverse mapping written here in NumPy: the
distortion is inverted by fixed-point iteration and the ray is intersected with the board plane
through the inverse of the plane homography [r1 r2 t]. Nothing here calls OpenCV's projection,
so a calibration that recovers this camera is checked against a truth it did not compute.
"""
from __future__ import annotations

import math

import numpy as np


def distort(x, y, k):
    k1, k2, p1, p2, k3 = k
    r2 = x * x + y * y
    radial = 1 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    return (x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x),
            y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y)


def undistort(xd, yd, k, iterations: int = 30):
    """Inverts `distort` by fixed-point iteration (converges for the mild lenses used here)."""
    k1, k2, p1, p2, k3 = k
    x, y = xd.copy(), yd.copy()
    for _ in range(iterations):
        r2 = x * x + y * y
        radial = 1 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
        dx = 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
        dy = p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
        x, y = (xd - dx) / radial, (yd - dy) / radial
    return x, y


def rot(rx_deg: float, ry_deg: float, rz_deg: float) -> np.ndarray:
    ax, ay, az = (math.radians(v) for v in (rx_deg, ry_deg, rz_deg))
    rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    return rz @ rx @ ry


def pose(rx: float, ry: float, rz: float, distance_mm: float, centre_mm, offset_mm=(0.0, 0.0)):
    """Board-to-camera (R, t): the board centre lands at (offset, distance) in camera coordinates."""
    r = rot(rx, ry, rz)
    c = np.array([centre_mm[0], centre_mm[1], 0.0])
    t = np.array([offset_mm[0], offset_mm[1], distance_mm]) - r @ c
    return r, t


def sample_bilinear(img: np.ndarray, px: np.ndarray, py: np.ndarray, outside: float) -> np.ndarray:
    h, w = img.shape
    x0, y0 = np.floor(px).astype(int), np.floor(py).astype(int)
    fx, fy = px - x0, py - y0
    inside = (x0 >= 0) & (y0 >= 0) & (x0 < w - 1) & (y0 < h - 1)
    x0c, y0c = np.clip(x0, 0, w - 2), np.clip(y0, 0, h - 2)
    v = (img[y0c, x0c] * (1 - fx) * (1 - fy) + img[y0c, x0c + 1] * fx * (1 - fy)
         + img[y0c + 1, x0c] * (1 - fx) * fy + img[y0c + 1, x0c + 1] * fx * fy)
    return np.where(inside, v, outside)


_RAYS: dict = {}


def rays(cam: dict, supersample: int) -> list:
    """Undistorted normalised coordinates of every sub-pixel sample: independent of the pose, so
    computed once per camera and reused."""
    key = (cam["fx"], cam["fy"], cam["cx"], cam["cy"], tuple(cam["k"]), tuple(cam["size"]), supersample)
    if key not in _RAYS:
        w, h = cam["size"]
        vv, uu = np.mgrid[0:h, 0:w].astype(float)
        offsets = [(i + 0.5) / supersample - 0.5 for i in range(supersample)]
        _RAYS[key] = [undistort((uu + ox - cam["cx"]) / cam["fx"], (vv + oy - cam["cy"]) / cam["fy"], cam["k"])
                      for oy in offsets for ox in offsets]
    return _RAYS[key]


def render(board_black: np.ndarray, px_per_mm: float, cam: dict, r: np.ndarray, t: np.ndarray,
           rng: np.random.Generator, noise: float = 2.0, blur_px: float = 0.8, supersample: int = 2):
    """One 8-bit luma frame of the board (True = black in `board_black`, origin at its top-left
    corner, x right, y down, in mm / px_per_mm), or a float luma map of the paper (`streaked`).
    cam: fx, fy, cx, cy, k (5), size (w, h)."""
    import cv2  # only for the optical blur, never for the projection
    w, h = cam["size"]
    paper = np.where(board_black, 25.0, 235.0) if board_black.dtype == bool else board_black.astype(float)
    hom = np.column_stack([r[:, 0], r[:, 1], t])
    hinv = np.linalg.inv(hom)
    acc = np.zeros((h, w))
    for x, y in rays(cam, supersample):
        wx = hinv[0, 0] * x + hinv[0, 1] * y + hinv[0, 2]
        wy = hinv[1, 0] * x + hinv[1, 1] * y + hinv[1, 2]
        ww = hinv[2, 0] * x + hinv[2, 1] * y + hinv[2, 2]
        visible = ww > 0  # points behind the camera are not seen
        bx, by = wx / np.where(visible, ww, 1) * px_per_mm - 0.5, wy / np.where(visible, ww, 1) * px_per_mm - 0.5
        acc += np.where(visible, sample_bilinear(paper, bx, by, 225.0), 225.0)
    img = acc / supersample ** 2
    if blur_px > 0:
        img = cv2.GaussianBlur(img, (0, 0), blur_px)
    img = img + rng.normal(0, noise, img.shape)
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def rodrigues(w: np.ndarray) -> np.ndarray:
    """Rotation matrices for rotation vectors w (... x 3), written out (no OpenCV)."""
    th = np.linalg.norm(w, axis=-1)[..., None, None]
    k = w / np.where(th[..., 0] > 0, th[..., 0], 1.0)
    kx = np.zeros(w.shape[:-1] + (3, 3))
    kx[..., 0, 1], kx[..., 0, 2], kx[..., 1, 2] = -k[..., 2], k[..., 1], -k[..., 0]
    kx = kx - np.swapaxes(kx, -1, -2)
    return np.eye(3) + np.sin(th) * kx + (1 - np.cos(th)) * kx @ kx


def render_moving(board_black: np.ndarray, px_per_mm: float, cam: dict, r: np.ndarray, t: np.ndarray,
                  rng: np.random.Generator, omega=(0.0, 0.0, 0.0), vel_mm_s=(0.0, 0.0, 0.0), exposure_s: float = 0.0,
                  readout_s: float = 0.0, steps: int = 5, noise: float = 2.0, blur_px: float = 0.8, supersample: int = 2):
    """A frame from a hand-held camera: rotating at `omega` (rad/s, camera axes) and moving at
    `vel_mm_s` while it exposes. Motion blur: the exposure is averaged over `steps` instants.
    Rolling shutter: row v is exposed `readout_s` x (v / h - 0.5) later than the middle row. (r, t)
    is the pose at the middle of the frame; each row's pose comes from its own homography."""
    import cv2  # only for the optical blur, never for the projection
    w, h = cam["size"]
    paper = np.where(board_black, 25.0, 235.0) if board_black.dtype == bool else board_black.astype(float)
    row_t = readout_s * ((np.arange(h) + 0.5) / h - 0.5)
    taus = [0.0] if steps < 2 or exposure_s <= 0 else list(np.linspace(-exposure_s / 2, exposure_s / 2, steps))
    acc = np.zeros((h, w))
    for tau in taus:
        tt = row_t + tau
        rm = rodrigues(np.outer(tt, omega))                       # h x 3 x 3
        rr = rm @ r
        tr = (rm @ t) + np.outer(tt, vel_mm_s)
        hinv = np.linalg.inv(np.stack([rr[:, :, 0], rr[:, :, 1], tr], axis=-1))[:, None]  # h x 1 x 3 x 3
        for x, y in rays(cam, supersample):
            wx = hinv[..., 0, 0] * x + hinv[..., 0, 1] * y + hinv[..., 0, 2]
            wy = hinv[..., 1, 0] * x + hinv[..., 1, 1] * y + hinv[..., 1, 2]
            ww = hinv[..., 2, 0] * x + hinv[..., 2, 1] * y + hinv[..., 2, 2]
            visible = ww > 0
            bx, by = wx / np.where(visible, ww, 1) * px_per_mm - 0.5, wy / np.where(visible, ww, 1) * px_per_mm - 0.5
            acc += np.where(visible, sample_bilinear(paper, bx, by, 225.0), 225.0)
    img = acc / (supersample ** 2 * len(taus))
    if blur_px > 0:
        img = cv2.GaussianBlur(img, (0, 0), blur_px)
    img = img + rng.normal(0, noise, img.shape)
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def streaked(board_black: np.ndarray, px_per_mm: float, rng: np.random.Generator, per_mm: float = 0.6,
             lift=(0.3, 0.6), width_mm=(0.15, 0.4)) -> np.ndarray:
    """Paper luma with inkjet nozzle streaks: lines of constant board x, brighter than the black by
    `lift` x the black-to-white swing, only where the paper is black. Defaults match the
    2026-11-14 print seen by camera 0 at 29 cm (1 to 2 px wide at 4.25 px/mm, +20 to +60 over
    a black of 57 and a white of 175) and reproduce its failure: plain detection loses corners."""
    luma = np.where(board_black, 25.0, 235.0)
    w = board_black.shape[1]
    for _ in range(int(per_mm * w / px_per_mm)):
        x0 = rng.uniform(0, w)
        a = int(x0)
        b = int(min(w, x0 + max(1.0, rng.uniform(*width_mm) * px_per_mm)))
        col = luma[:, a:b]
        col[board_black[:, a:b]] += rng.uniform(*lift) * 210.0
    return luma


def project(cam: dict, r: np.ndarray, t: np.ndarray, pts_mm: np.ndarray) -> np.ndarray:
    """Board points (N x 2, mm) to pixels through the same model, for the tests' truth."""
    p = (r @ np.column_stack([pts_mm, np.zeros(len(pts_mm))]).T).T + t
    x, y = distort(p[:, 0] / p[:, 2], p[:, 1] / p[:, 2], cam["k"])
    return np.column_stack([cam["fx"] * x + cam["cx"], cam["fy"] * y + cam["cy"]])


# 15 poses for a 200 x 160 mm board: varied distance, tilt and roll, all keeping it mostly in view.
POSES = [(0, 0, 0, 320), (18, 0, 0, 330), (-18, 0, 0, 330), (0, 20, 0, 340), (0, -20, 0, 340),
         (15, 15, 5, 360), (-15, 15, -5, 360), (15, -15, 90, 420), (-12, -18, 90, 430), (0, 0, 90, 400),
         (22, 8, 2, 380), (-8, 24, -3, 390), (10, -24, 4, 390), (-22, -8, 0, 370), (5, 5, 180, 350)]
