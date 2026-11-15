"""Tests for the screen calibration target (screen_target.py)."""
import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HAS_ALL = all(importlib.util.find_spec(m) is not None for m in ("numpy", "cv2"))


@unittest.skipUnless(HAS_ALL, "needs numpy and cv2")
class ScreenTarget(unittest.TestCase):
    def test_corners_sit_on_whole_pixel_square_edges(self):
        import numpy as np
        import calib_core as cc
        import make_target as mt
        import screen_target as st
        img, geo = st.board_image(1920, 1080, 120)
        board = mt.board_object(mt.default_spec()["board"])
        corners, ids = cc.detect_corners(img, board)
        self.assertEqual(len(ids), 63)
        k = np.column_stack([ids % 9 + 1, ids // 9 + 1])  # inner corner (column, row) from the board's id order
        want = np.array(geo["origin_px"]) + k * geo["square_px"] - 0.5  # pixel centres at integers
        self.assertLess(np.abs(corners - want).max(), 0.05)

    def test_marker_cells_must_be_whole_pixels(self):
        import screen_target as st
        with self.assertRaises(ValueError):
            st.board_image(1920, 1080, 125)

    def test_a_scaled_screen_fails_the_exact_check(self):
        import cv2
        import screen_target as st
        img, _ = st.board_image(1920, 1080, 120)
        self.assertTrue(st.compare(img.copy(), img)["ok"])
        small = cv2.resize(img, None, fx=0.95, fy=0.95, interpolation=cv2.INTER_AREA)
        canvas = img.copy()
        canvas[:] = 255
        canvas[:small.shape[0], :small.shape[1]] = small
        self.assertFalse(st.compare(canvas, img)["ok"])
        self.assertFalse(st.compare(small, img)["ok"])


if __name__ == "__main__":
    unittest.main()
