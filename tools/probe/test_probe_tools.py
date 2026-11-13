"""Tests for the dumpsys parser and the Gate 1 cross-check, on real captured dumps."""
import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import crosscheck  # noqa: E402
import dumpsys_camera  # noqa: E402

NOTE8 = (HERE / "fixtures" / "dumpsys_sm-n950f_lineage20.txt").read_text(encoding="utf-8")
NOTE10 = (HERE / "fixtures" / "dumpsys_sm-n970f_logical20_excerpt.txt").read_text(encoding="utf-8")

# What the probe app is expected to report for the Note8 main camera, typed from the
# CameraCharacteristics conventions in docs/units/device-probe.md (not copied from dumpsys).
NOTE8_CAMERA0 = {
    "android.lens.facing": 1,
    "android.lens.info.minimumFocusDistance": 10.0,
    "android.lens.info.availableFocalLengths": [4.3],
    "android.sensor.info.physicalSize": [5.645, 4.234],
    "android.sensor.info.pixelArraySize": [4032, 3024],
    "android.sensor.info.activeArraySize": [0, 0, 4032, 3024],
}


def probe_with(chars: dict, cam_id: str = "0", physical_ids=None) -> dict:
    return {"cameras": {"entries": [{"id": cam_id, "characteristics": chars, "physical_ids": physical_ids}]}}


class Parser(unittest.TestCase):
    def test_note8_has_exactly_cameras_0_and_1(self):
        self.assertEqual(sorted(dumpsys_camera.parse(NOTE8)), ["0", "1"])

    def test_single_and_multi_line_values(self):
        cam0 = dumpsys_camera.parse(NOTE8)["0"]
        self.assertEqual(cam0["android.lens.facing"].tokens, ["BACK"])
        self.assertEqual(cam0["android.sensor.info.physicalSize"].tokens, ["5.64499998", "4.23400021"])
        fps = cam0["android.control.aeAvailableTargetFpsRanges"]
        self.assertEqual((fps.type, fps.count, len(fps.tokens)), ("int32", 12, 12))

    def test_rational_becomes_one_token(self):
        cam0 = dumpsys_camera.parse(NOTE8)["0"]
        self.assertEqual(cam0["android.control.aeCompensationStep"].tokens, ["50/100"])

    def test_dumpstate_blocks_are_not_static_metadata(self):
        # "dumpState" sections follow each static block and must not leak tags into it.
        cam1 = dumpsys_camera.parse(NOTE8)["1"]
        self.assertEqual(cam1["android.lens.facing"].tokens, ["FRONT"])

    def test_note10_physical_ids_decode(self):
        entry = dumpsys_camera.parse(NOTE10)["20"]["android.logicalMultiCamera.physicalIds"]
        self.assertEqual(dumpsys_camera.decode_byte_string_list(entry.tokens), ["0", "52", "2"])


class CrossCheck(unittest.TestCase):
    def test_matching_probe_passes(self):
        report = crosscheck.crosscheck(probe_with(NOTE8_CAMERA0), NOTE8)
        self.assertEqual(report["verdict"], "pass", report)
        self.assertEqual(report["only_in_dumpsys"], ["1"])

    def test_one_wrong_value_fails(self):
        chars = copy.deepcopy(NOTE8_CAMERA0)
        chars["android.lens.info.minimumFocusDistance"] = 8.0
        self.assertEqual(crosscheck.crosscheck(probe_with(chars), NOTE8)["verdict"], "fail")

    def test_wrong_facing_fails(self):
        chars = dict(NOTE8_CAMERA0, **{"android.lens.facing": 0})
        self.assertEqual(crosscheck.crosscheck(probe_with(chars), NOTE8)["verdict"], "fail")

    def test_pose_present_only_in_probe_fails(self):
        chars = dict(NOTE8_CAMERA0, **{"android.lens.poseTranslation": [0.0, 0.0, 0.0]})
        self.assertEqual(crosscheck.crosscheck(probe_with(chars), NOTE8)["verdict"], "fail")

    def test_no_shared_camera_is_could_not_tell(self):
        report = crosscheck.crosscheck(probe_with(NOTE8_CAMERA0, cam_id="7"), NOTE8)
        self.assertEqual(report["verdict"], "could_not_tell")

    def test_physical_ids_compared(self):
        ok = crosscheck.crosscheck(probe_with({}, "20", ["2", "0", "52"]), NOTE10)
        bad = crosscheck.crosscheck(probe_with({}, "20", ["0", "2"]), NOTE10)
        self.assertEqual((ok["matches"], ok["mismatches"]), (3, 0))
        self.assertEqual(bad["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()
