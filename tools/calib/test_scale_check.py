"""Tests for scale_check.py (docs/units/microscope-scale.md) on the independent synthetic renderer,
with the contract's negative controls."""
import importlib.util
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HAS_ALL = all(importlib.util.find_spec(m) is not None for m in ("numpy", "cv2"))
# Camera 0 as calibrated (163037-f2e7), focused at 300 mm: fx from the thin lens with breathing.
K_DIST = [0.149, -0.386, 0.0, 0.0003, 0.0]


def cam_at(distance_mm):
    import scale_check as sk
    fx = sk.fx_px(sk.camera0(1440), 1000.0 / distance_mm)
    return {"fx": fx, "fy": fx, "cx": 733.0, "cy": 536.0, "k": K_DIST, "size": (1440, 1080)}


def frame(distance_mm, ry_deg=0.0, offset=(0.0, 0.0), seed=3):
    """Rendered A4 board (20 mm squares) and the true µm per px at the centroid's ray."""
    import numpy as np
    import calib_core as cc
    import make_target as mt
    import synth_camera as sc
    b = mt.default_spec()["board"]
    bmp, board = mt.board_bitmap(b), mt.board_object(b)
    cam = cam_at(distance_mm)
    r, t = sc.pose(0.0, ry_deg, 0.0, distance_mm, centre_mm=(100, 80), offset_mm=offset)
    img = sc.render(bmp, mt.PX_PER_MM, cam, r, t, np.random.default_rng(seed))
    corners, ids = cc.detect_corners(img, board)
    return cam, board, corners, ids, r, t


def true_um(cam, r, t, centroid_px):
    """Depth where the centroid's (undistorted) ray meets the board plane, over fx."""
    import numpy as np
    x = np.array([(centroid_px[0] - cam["cx"]) / cam["fx"], (centroid_px[1] - cam["cy"]) / cam["fy"], 1.0])
    n = r[:, 2]
    z = (n @ t) / (n @ x)
    return z * 1000.0 / cam["fx"]


@unittest.skipUnless(HAS_ALL, "needs numpy and cv2")
class BoardScale(unittest.TestCase):
    def check(self, distance, ry=0.0, offset=(0.0, 0.0), tol=0.003):
        import numpy as np
        import scale_check as sk
        cam, board, corners, ids, r, t = frame(distance, ry, offset)
        k = np.array([[cam["fx"], 0, cam["cx"]], [0, cam["fy"], cam["cy"]], [0, 0, 1]])
        um, centroid = sk.board_um_per_px(corners, ids, board, 1.0, k, np.array(K_DIST))
        truth = true_um(cam, r, t, centroid)
        self.assertLess(abs(um / truth - 1), tol, f"{um} vs {truth}")
        return um, truth, (cam, board, corners, ids, k)

    def test_square_on(self):
        self.check(300.0)

    def test_tilted_and_off_centre(self):
        self.check(300.0, ry=20.0, offset=(40.0, -20.0))

    def test_without_undistortion_is_biased(self):
        """Negative control: ignoring k1 off-centre must be visibly wrong (the reason to undistort)."""
        import numpy as np
        import scale_check as sk
        _, truth, (cam, board, corners, ids, k) = self.check(300.0, offset=(70.0, 0.0))
        um, _ = sk.board_um_per_px(corners, ids, board, 1.0, k, np.zeros(5))
        self.assertGreater(abs(um / truth - 1), 0.005)  # 0.9 % with the centroid ~270 px off-centre

    def test_wrong_square_size_is_five_percent_off(self):
        import numpy as np
        import scale_check as sk
        _, truth, (cam, board, corners, ids, k) = self.check(300.0)
        um, _ = sk.board_um_per_px(corners, ids, board, 21 / 20, k, np.array(K_DIST))
        self.assertAlmostEqual(um / truth - 1, 0.05, delta=0.003)


class Model(unittest.TestCase):
    def test_hand_calculation(self):
        import scale_check as sk
        lens = sk.camera0(1440)
        self.assertAlmostEqual(lens[0], 4.40616, delta=0.0001)
        self.assertAlmostEqual(sk.um_per_px(lens, 10.0), 85.049, delta=0.085)
        self.assertIsNone(sk.um_per_px(lens, 0.0))
        self.assertIsNone(sk.um_per_px(lens, 300.0))
        self.assertAlmostEqual(sk.predict("no-breathing", 10.0, 1440) / 85.049 - 1, 0.0346, delta=0.001)
        self.assertAlmostEqual(sk.predict("nominal", 10.0, 1440) / 85.049 - 1, 0.0258, delta=0.001)


def row(d, err, af=2, corners=40, burst=0):
    pred = 1e6 / (d * 1176.0)
    return {"burst": burst, "af_state": af, "corners": corners, "focus_diopters": d,
            "pred_um": pred, "board_um": pred / (1 + err)}


class Judge(unittest.TestCase):
    def frames(self, err=0.005):
        return [row(d, err, burst=b) for b, d in enumerate((10.0, 6.7, 5.0)) for _ in range(4)]

    def test_passes_good_frames(self):
        import scale_check as sk
        res = sk.judge(self.frames(), "calibrated")
        self.assertEqual(res["verdict"], "pass", res)
        self.assertEqual(res["distances"], 3)

    def test_one_frame_over_two_percent_fails(self):
        import scale_check as sk
        f = self.frames()
        f[0]["board_um"] = f[0]["pred_um"] / 1.03
        self.assertEqual(sk.judge(f, "calibrated")["verdict"], "fail")

    def test_median_bias_fails(self):
        import scale_check as sk
        self.assertEqual(sk.judge(self.frames(err=0.015), "calibrated")["verdict"], "fail")

    def test_unfocused_frames_are_not_judged(self):
        import scale_check as sk
        f = self.frames()
        for r in f[4:]:
            r["af_state"] = 1  # PASSIVE_SCAN
        res = sk.judge(f, "calibrated")
        self.assertEqual(res["verdict"], "cannot judge")  # one distance left

    def test_too_few_distances_cannot_judge(self):
        import scale_check as sk
        f = [row(10.0, 0.0) for _ in range(8)]
        self.assertEqual(sk.judge(f, "calibrated")["verdict"], "cannot judge")

    def test_no_breathing_control_uses_near_frames_only(self):
        import scale_check as sk
        f = self.frames(err=0.0) + [row(9.0, 0.0) for _ in range(3)]
        res = sk.judge(f, "no-breathing")
        self.assertEqual(res["frames_judged"], 7)  # 4 at 10 cm, 3 at 11.1 cm
        self.assertTrue(all(math.isfinite(r["err"]) for r in res["per_frame"] if r["judged"]))


if __name__ == "__main__":
    unittest.main()
