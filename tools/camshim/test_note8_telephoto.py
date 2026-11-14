"""Tests for the pure parts of note8_telephoto.py: the command plans and the output parsers."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import note8_telephoto as t  # noqa: E402

NOTE8_DUMPSYS_HEAD = (Path(__file__).resolve().parents[1] / "probe" / "fixtures" / "dumpsys_sm-n950f_lineage20.txt").read_text(encoding="utf-8")


class Plans(unittest.TestCase):
    def test_install_labels_before_mounting_and_restarts_provider_first(self):
        steps = [s[1] for s in t.install_plan()]
        self.assertLess(steps.index(f"chcon {t.LABEL} {t.REMOTE_SHIM}"), steps.index(f"mount -o bind {t.REMOTE_SHIM} {t.TARGET}"))
        self.assertEqual(steps[-2:], ["setprop ctl.restart vendor.camera-provider-2-5", "setprop ctl.restart cameraserver"])

    def test_nothing_is_written_under_system(self):
        for step in t.install_plan() + t.revert_plan():
            cmd = step[1]
            self.assertFalse(cmd.startswith(("cp ", "mv ", "rm ")), cmd)
            self.assertNotIn("remount", cmd)
            self.assertNotIn("disable-verity", cmd)

    def test_revert_unmounts_the_same_target(self):
        self.assertEqual(t.revert_plan()[0], ["shell", f"umount {t.TARGET}"])
        self.assertEqual(t.revert_plan()[1], ["shell", f"umount {t.LIB_TARGET}"])

    def test_patched_lib_is_mounted_only_when_asked_and_before_the_restart(self):
        plain = [s[1] for s in t.install_plan()]
        with_lib = [s[1] for s in t.install_plan(with_lib=True)]
        mount_lib = f"mount -o bind {t.REMOTE_LIB} {t.LIB_TARGET}"
        self.assertNotIn(mount_lib, plain)
        self.assertLess(with_lib.index(mount_lib), with_lib.index("setprop ctl.restart vendor.camera-provider-2-5"))


class Parsers(unittest.TestCase):
    def test_camera_count_from_real_note8_dumpsys(self):
        self.assertEqual(t.camera_count(NOTE8_DUMPSYS_HEAD), 2)
        self.assertIsNone(t.camera_count("nothing here"))

    def test_shim_mounted_matches_the_mount_point_exactly(self):
        line = f"/dev/block/dm-0 {t.TARGET} ext4 ro,seclabel 0 0"
        self.assertTrue(t.shim_mounted("tmpfs /dev tmpfs rw 0 0\n" + line))
        self.assertFalse(t.shim_mounted(f"/dev/block/dm-0 {t.TARGET}.bak ext4 ro 0 0"))
        self.assertFalse(t.shim_mounted(""))


if __name__ == "__main__":
    unittest.main()
