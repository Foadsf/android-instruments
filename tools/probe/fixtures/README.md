# Probe fixtures

| File | Provenance |
|---|---|
| `dumpsys_sm-n950f_lineage20.txt` | Verbatim `adb shell dumpsys media.camera` from a Galaxy Note8 SM-N950F, LineageOS 20.0-20250628-UNOFFICIAL-greatlte (Android 13), captured 2026-11-13. Same bytes as `results/sm-n950f/dumpsys_media_camera_20261113.txt`. |
| `dumpsys_sm-n970f_logical20_excerpt.txt` | Lines 2 to 8 are verbatim `grep -A 6 android.logicalMultiCamera.physicalIds` output from a Galaxy Note10 SM-N970F (stock One UI, Android 12), pasted in an earlier chat on 2026-11-09. Line 1, the block header, was added by hand in the format the same phone prints (`device@3.5/legacy/<id>`); the camera ID `20` in it is an assumption, not observed. Use it only for value decoding, not for ID mapping. |
