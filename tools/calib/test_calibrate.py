"""Tests for the camera calibration (docs/units/camera-calibration.md) on the independent
synthetic renderer (synth_camera.py), with the contract's negative controls."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HAS_ALL = all(importlib.util.find_spec(m) is not None for m in ("numpy", "cv2"))
WIDE = {"fx": 1100.0, "fy": 1100.0, "cx": 725.0, "cy": 535.0, "k": [0.08, -0.15, 0.001, -0.0005, 0.0],
        "size": (1440, 1080)}
TELE = {"fx": 2050.0, "fy": 2050.0, "cx": 718.0, "cy": 542.0, "k": [0.02, 0.0, 0.0, 0.0, 0.0], "size": (1440, 1080)}
BARREL = {"fx": 1100.0, "fy": 1100.0, "cx": 720.0, "cy": 540.0, "k": [0.10, 0.0, 0.0, 0.0, 0.0], "size": (1440, 1080)}


def views_for(cam, poses, scale=1.0, seed=7, streaks=False, destreak=True, truth=False):
    """Renders the board through `cam` at each pose and returns detected views (and the images).
    streaks: the paper carries nozzle streaks like the 2026-11-14 print (sharper optics, blur
    0.6 px). truth: each view also carries the true corner pixels ('true')."""
    import numpy as np
    import calib_core as cc
    import make_target as mt
    import synth_camera as sc
    b = mt.default_spec()["board"]
    bmp, board = mt.board_bitmap(b), mt.board_object(b)
    rng = np.random.default_rng(seed)
    out, imgs = [], []
    for i, p in enumerate(poses):
        r, t = sc.pose(*p, centre_mm=(100, 80))
        paper = sc.streaked(bmp, mt.PX_PER_MM, rng) if streaks else bmp
        img = sc.render(paper, mt.PX_PER_MM, cam, r, t, rng, blur_px=0.6 if streaks else 0.8)
        corners, ids = cc.detect_corners(img, board, destreak=destreak)
        imgs.append(img)
        if ids is not None and len(ids) >= cc.MIN_CORNERS:
            v = {"pose": i, "obj": cc.object_points(board, ids, (scale, scale)), "img": corners, "ids": ids,
                 "size": cam["size"]}
            if truth:
                v["true"] = sc.project(cam, r, t, cc.object_points(board, ids)[:, :2])
            out.append(v)
    return out, imgs


@unittest.skipUnless(HAS_ALL, "needs numpy and cv2")
class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import synth_camera as sc
        cls.views, _ = views_for(WIDE, sc.POSES)

    def test_recovers_the_known_camera(self):
        import calib_core as cc
        train, ev = cc.split_views(len(self.views))
        cal = cc.calibrate([self.views[i] for i in train], WIDE["size"])
        k, d, s = cal["K"], cal["dist"], cal["std"]
        self.assertLess(abs(k[0, 0] / WIDE["fx"] - 1), 0.003)
        self.assertLess(abs(k[1, 1] / WIDE["fy"] - 1), 0.003)
        self.assertLess(abs(k[0, 2] - WIDE["cx"]), 2.0)
        self.assertLess(abs(k[1, 2] - WIDE["cy"]), 2.0)
        self.assertLess(abs(d[0] - WIDE["k"][0]), 0.01)
        for name, est, true in (("fx", k[0, 0], WIDE["fx"]), ("cx", k[0, 2], WIDE["cx"]), ("cy", k[1, 2], WIDE["cy"]),
                                ("k1", d[0], WIDE["k"][0])):
            self.assertLessEqual(abs(est - true), 3 * s[name] + 1e-9, name)
        self.assertLess(cc.reprojection_rms([self.views[i] for i in ev], k, d), 0.5)

    def test_straightness_passes_with_the_distortion_model(self):
        import calib_core as cc
        cal = cc.calibrate(self.views, WIDE["size"])
        self.assertLess(cc.straightness(self.views, [v["ids"] for v in self.views], cal["K"], cal["dist"], 10), 0.15)

    def test_halves_refuse_overlapping_sets(self):
        import calib_core as cc
        with self.assertRaises(ValueError):
            cc.halves(10, [0, 2, 4], [4, 5, 6])

    def test_imu_rotation_recovers_a_known_offset(self):
        import numpy as np
        import calib_core as cc
        import synth_camera as sc
        rng = np.random.default_rng(3)
        up = rng.normal(size=(6, 3))
        r_true = sc.rot(1.5, -2.0, 0.7)
        r, res = cc.imu_rotation(up, (r_true @ up.T).T)
        self.assertLess(np.abs(r - r_true).max(), 1e-9)
        self.assertLess(res, 1e-4)  # degrees; arccos near 1 limits precision to ~1e-6


@unittest.skipUnless(HAS_ALL, "needs numpy and cv2")
class NegativeControlsAndPairs(unittest.TestCase):
    def test_ignoring_distortion_fails_straightness_and_focal_length(self):
        import calib_core as cc
        import synth_camera as sc
        views, _ = views_for(BARREL, sc.POSES)
        cal = cc.calibrate(views, BARREL["size"], fix_distortion=True)
        self.assertGreater(cc.straightness(views, [v["ids"] for v in views], cal["K"], cal["dist"], 10), 0.15)
        self.assertGreater(abs(cal["K"][0, 0] / BARREL["fx"] - 1), 0.003)

    def test_known_displacement_and_a_wrong_square_size(self):
        import calib_core as cc
        import synth_camera as sc
        calib_views, _ = views_for(WIDE, sc.POSES)
        cal = cc.calibrate(calib_views, WIDE["size"])
        for scale, should_pass in ((1.0, True), (21.0 / 20.0, False)):
            pair, _ = views_for(WIDE, [(0, 0, 0, 320), (0, 0, 0, 420)], scale=scale, seed=11)
            d = [cc.wall_distance_tilt(*cc.solve_pose(v, cal["K"], cal["dist"]))[0] for v in pair]
            self.assertEqual(abs(abs(d[1] - d[0]) - 100.0) <= 1.5, should_pass, d)

    def test_ncc_scale_recovers_the_telephoto_ratio(self):
        import calib_core as cc
        poses = [(0, 0, 0, 400)]
        _, wide = views_for(WIDE, poses, seed=21)
        _, tele = views_for(TELE, poses, seed=22)
        cal_w = {"K": cc_k(WIDE), "dist": cc_d(WIDE)}
        cal_t = {"K": cc_k(TELE), "dist": cc_d(TELE)}
        s, _ = cc.ncc_ratio(wide[0], tele[0], cal_w, cal_t)
        self.assertLess(abs(s / (TELE["fx"] / WIDE["fx"]) - 1), 0.01, s)


@unittest.skipUnless(HAS_ALL, "needs numpy and cv2")
class StreakedPrint(unittest.TestCase):
    """The existing 2026-11-14 print has nozzle streaks; there will be no reprint."""

    def test_destreak_recovers_the_corners_streaks_hide_without_bias(self):
        import numpy as np
        import synth_camera as sc
        poses = sc.POSES[:6]
        plain, _ = views_for(WIDE, poses, seed=51, streaks=True, destreak=False)
        clean, _ = views_for(WIDE, poses, seed=51, streaks=True, truth=True)
        n_plain = sum(len(v["ids"]) for v in plain) / len(poses)
        n_clean = sum(len(v["ids"]) for v in clean) / len(poses)
        self.assertLess(n_plain, 0.8 * 63, n_plain)  # the failure seen on the real print
        self.assertGreaterEqual(n_clean, 0.9 * 63, n_clean)
        err = np.concatenate([v["img"] - v["true"] for v in clean])
        self.assertLess(np.abs(err.mean(0)).max(), 0.05, err.mean(0))
        self.assertLess(float(np.sqrt((err ** 2).sum(1).mean())), 0.3)

    def test_calibration_on_streaked_views_meets_the_contract(self):
        import calib_core as cc
        import synth_camera as sc
        views, _ = views_for(WIDE, sc.POSES, seed=41, streaks=True)
        train, ev = cc.split_views(len(views))
        cal = cc.calibrate([views[i] for i in train], WIDE["size"])
        k, d = cal["K"], cal["dist"]
        self.assertLess(abs(k[0, 0] / WIDE["fx"] - 1), 0.003)
        self.assertLess(max(abs(k[0, 2] - WIDE["cx"]), abs(k[1, 2] - WIDE["cy"])), 2.0)
        self.assertLess(abs(d[0] - WIDE["k"][0]), 0.01)
        self.assertLess(cc.reprojection_rms([views[i] for i in ev], k, d), 0.5)
        full = cc.calibrate(views, WIDE["size"])
        self.assertLess(cc.straightness(views, [v["ids"] for v in views], full["K"], full["dist"], 10), 0.15)

    def test_ignoring_distortion_still_fails_straightness_on_streaked_views(self):
        import calib_core as cc
        import synth_camera as sc
        views, _ = views_for(BARREL, sc.POSES, seed=43, streaks=True)
        cal = cc.calibrate(views, BARREL["size"], fix_distortion=True)
        self.assertGreater(cc.straightness(views, [v["ids"] for v in views], cal["K"], cal["dist"], 10), 0.15)


def hand_held_views(cam, n, gate, exposure_s, readout_s, seed, steps=3):
    """n views from a hand-held camera: random tilts within 25 deg, some on its side, and in each
    frame a rotation rate of 0.3 to 1 x `gate` (rad/s) in a random direction, about a pivot up to
    400 mm away (the wrist or elbow), so the camera also translates. Distances keep the 200 mm
    board's size in view as the 255 mm screen board at 40 to 60 cm (camera 0) or 70 to 90 cm (2)."""
    import numpy as np
    import calib_core as cc
    import make_target as mt
    import synth_camera as sc
    b = mt.default_spec()["board"]
    bmp, board = mt.board_bitmap(b), mt.board_object(b)
    rng = np.random.default_rng(seed)
    far = (560, 700) if cam["fx"] > 1500 else (320, 470)
    out = []
    for i in range(n):
        rx, ry = rng.uniform(-25, 25, 2)
        rz = rng.choice([0, 0, 0, 90]) + rng.uniform(-8, 8)
        r, t = sc.pose(rx, ry, rz, rng.uniform(*far), centre_mm=(100, 80), offset_mm=tuple(rng.uniform(-15, 15, 2)))
        d, lever = rng.normal(size=3), rng.normal(size=3)
        om = d / np.linalg.norm(d) * gate * rng.uniform(0.3, 1.0)
        vel = np.cross(om, lever / np.linalg.norm(lever) * rng.uniform(0, 400))
        img = sc.render_moving(bmp, mt.PX_PER_MM, cam, r, t, rng, om, vel, exposure_s, readout_s, steps=steps)
        c, ids = cc.detect_corners(img, board)
        if ids is not None and len(ids) >= cc.MIN_CORNERS:
            out.append({"pose": i, "obj": cc.object_points(board, ids), "img": c, "ids": ids, "size": cam["size"]})
    return out


def contract_errors(views, cam) -> dict:
    """The synthetic thresholds' quantities: focal and centre error, k1 error, held-out RMS, straightness."""
    import calib_core as cc
    train, ev = cc.split_views(len(views))
    cal = cc.calibrate([views[i] for i in train], cam["size"])
    k, d = cal["K"], cal["dist"]
    full = cc.calibrate(views, cam["size"])
    return {"fx_rel": abs(k[0, 0] / cam["fx"] - 1), "c_px": max(abs(k[0, 2] - cam["cx"]), abs(k[1, 2] - cam["cy"])),
            "k1": abs(d[0] - cam["k"][0]), "held": cc.reprojection_rms([views[i] for i in ev], k, d),
            "straight": cc.straightness(views, [v["ids"] for v in views], full["K"], full["dist"], 10)}


@unittest.skipUnless(HAS_ALL, "needs numpy and cv2")
class HandHeld(unittest.TestCase):
    """Hand-held amendment: frames kept only when the gyro stayed under the camera's limit over the
    exposure and readout: 0.04 rad/s for camera 0, 0.02 for camera 2. Camera 2 is the hard case
    (longest focal length; its bridge reports no exposure: 40 ms exposure and 33 ms readout assumed)."""

    def test_camera_2_within_the_gyro_gate_meets_the_contract(self):
        e = contract_errors(hand_held_views(TELE, 16, 0.02, 0.040, 0.033, seed=61), TELE)
        self.assertLess(e["fx_rel"], 0.003, e)
        self.assertLess(e["c_px"], 2.0, e)
        self.assertLess(e["k1"], 0.01, e)
        self.assertLess(e["held"], 0.8, e)
        self.assertLess(e["straight"], 0.15, e)

    def test_camera_0_within_its_looser_gate_meets_the_contract(self):
        # Camera 0 as run: 8 ms exposure cap, 32 ms skew (153949-0113), gate 0.04 rad/s.
        e = contract_errors(hand_held_views(WIDE, 16, 0.04, 0.008, 0.032, seed=62), WIDE)
        self.assertLess(e["fx_rel"], 0.003, e)
        self.assertLess(e["c_px"], 2.0, e)
        self.assertLess(e["k1"], 0.01, e)
        self.assertLess(e["held"], 0.5, e)
        self.assertLess(e["straight"], 0.15, e)

    def test_free_hand_motion_fails_the_contract(self):
        # Negative control: 0.2 rad/s, an arm moving freely, must not pass as a calibration.
        e = contract_errors(hand_held_views(TELE, 16, 0.2, 0.040, 0.033, seed=61), TELE)
        self.assertTrue(e["c_px"] > 2.0 or e["k1"] > 0.01 or e["held"] > 0.8 or e["straight"] > 0.15, e)
        self.assertGreater(e["straight"], 0.15, e)


def cc_k(cam):
    import numpy as np
    return np.array([[cam["fx"], 0, cam["cx"]], [0, cam["fy"], cam["cy"]], [0, 0, 1.0]])


def cc_d(cam):
    import numpy as np
    return np.array(cam["k"], float)


@unittest.skipUnless(HAS_ALL, "needs numpy and cv2")
class SeriesCli(unittest.TestCase):
    def write_series(self, root: Path, n_poses: int, moved=(), repeat=()):
        """repeat: poses whose image is the previous pose's again (a hand-held sweep's near-duplicate)."""
        import numpy as np
        import synth_camera as sc
        _, imgs = views_for(WIDE, sc.POSES[:n_poses], seed=31)
        for i in repeat:
            imgs[i] = imgs[i - 1]
        poses = []
        for i, img in enumerate(imgs):
            d = root / f"pose_{i:02d}" / "cam0"
            d.mkdir(parents=True)
            frame = np.concatenate([img.ravel(), np.full(img.size // 2, 128, np.uint8)])
            frame.tofile(d / "frame_00.yuv")
            (d / "burst.json").write_text(json.dumps({"width": 1440, "height": 1080, "frames": 1}))
            poses.append({"index": i, "dir": f"pose_{i:02d}", "status": "moved" if i in moved else "ok",
                          "accel_mean": [9.8, 0.1, 1.0], "bursts": {"0": f"pose_{i:02d}/cam0"}})
        (root / "series.json").write_text(json.dumps({"run_id": "test", "cameras": ["0"], "poses": poses}))

    def test_too_few_views_cannot_be_judged(self):
        import calibrate
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "s"
            self.write_series(root, 5)
            self.assertEqual(calibrate.main([str(root), "--out", str(Path(d) / "r.json")]), 3)

    def test_a_moved_pose_is_dropped_and_named(self):
        import calibrate
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "s"
            self.write_series(root, 9, moved=(2,))
            out = Path(d) / "r.json"
            calibrate.main([str(root), "--out", str(out)])
            report = json.loads(out.read_text())
            self.assertIn({"pose": 2, "camera": "all", "reason": "moved"}, report["dropped"])

    def test_a_camera_0_pose_off_its_requested_focus_is_dropped(self):
        import calibrate
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "s"
            self.write_series(root, 9)
            s = json.loads((root / "series.json").read_text())
            s["focus_diopters"] = 3.5
            for p in s["poses"]:
                p["cameras"] = {"0": {"focus_diopters": 3.5 if p["index"] != 4 else 3.2}}
            (root / "series.json").write_text(json.dumps(s))
            out = Path(d) / "r.json"
            calibrate.main([str(root), "--out", str(out)])
            reasons = [x for x in json.loads(out.read_text())["dropped"] if x["pose"] == 4]
            self.assertEqual(len(reasons), 1)
            self.assertIn("focus 3.2", reasons[0]["reason"])

    def test_a_hand_held_camera_on_another_clock_fails(self):
        import calibrate
        ok = calibrate.clock_checks({"per_camera": {"0": {"arrival_lag_ms": {"median": 42.0}}}})
        self.assertTrue(ok[0]["ok"])
        for lag in (-3.0, 5000.0, None):  # negative control: a frame "before" its exposure, or far off
            bad = calibrate.clock_checks({"per_camera": {"2": {"arrival_lag_ms": {"median": lag}}}})
            self.assertFalse(bad[0]["ok"], lag)

    def test_a_hand_held_near_duplicate_is_dropped_and_named(self):
        import calibrate
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "s"
            self.write_series(root, 10, repeat=(5,))
            s = json.loads((root / "series.json").read_text())
            out = Path(d) / "r.json"
            calibrate.main([str(root), "--out", str(out)])  # a still series keeps it (distinct poses by design)
            self.assertFalse([x for x in json.loads(out.read_text())["dropped"] if x["pose"] == 5])
            s["capture"] = "hand-held sweep"
            (root / "series.json").write_text(json.dumps(s))
            calibrate.main([str(root), "--out", str(out)])
            dropped = [x for x in json.loads(out.read_text())["dropped"] if x["pose"] == 5]
            self.assertEqual(len(dropped), 1)
            self.assertIn("near-duplicate of pose 4", dropped[0]["reason"])


if __name__ == "__main__":
    unittest.main()
