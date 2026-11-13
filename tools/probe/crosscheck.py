#!/usr/bin/env python3
"""Gate 1 spot check: does the probe app's JSON agree with `dumpsys media.camera`?

The two are independent paths to the same facts: the app reads CameraCharacteristics through
the public Camera2 API, dumpsys prints the camera service's own metadata. For every camera both
sides know, a fixed list of fields is compared.

Exit codes: 0 at least MIN_MATCHES fields agree and none disagree; 1 a field disagrees;
3 could not tell (nothing comparable); 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dumpsys_camera  # noqa: E402

MIN_MATCHES = 3
FACING = {0: "FRONT", 1: "BACK", 2: "EXTERNAL"}
NUMERIC_FIELDS = [
    "android.lens.info.minimumFocusDistance",
    "android.lens.info.availableFocalLengths",
    "android.sensor.info.physicalSize",
    "android.sensor.info.pixelArraySize",
    "android.sensor.info.activeArraySize",
]
PRESENCE_FIELDS = ["android.lens.poseTranslation", "android.lens.intrinsicCalibration"]


def flatten(value) -> list:
    if isinstance(value, list):
        return [x for v in value for x in flatten(v)]
    return [value]


def numbers_equal(probe_value, tokens: list[str]) -> bool:
    ours = [float(x) for x in flatten(probe_value)]
    theirs = [float(t) for t in tokens]
    return len(ours) == len(theirs) and all(
        math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-6) for a, b in zip(ours, theirs))


def compare_camera(chars: dict, physical_ids: list | None, dump: dict) -> list[dict]:
    rows = []

    def row(fieldname, verdict, probe=None, dumpsys=None):
        rows.append({"field": fieldname, "verdict": verdict, "probe": probe, "dumpsys": dumpsys})

    facing = chars.get("android.lens.facing")
    if facing is not None and "android.lens.facing" in dump:
        theirs = dump["android.lens.facing"].tokens
        row("android.lens.facing", "match" if [FACING.get(facing)] == theirs else "mismatch", facing, theirs)
    for name in NUMERIC_FIELDS:
        ours, theirs = chars.get(name), dump.get(name)
        if ours is None and theirs is None:
            continue
        if ours is None or theirs is None:
            row(name, "mismatch", ours, theirs.tokens if theirs else None)
        else:
            row(name, "match" if numbers_equal(ours, theirs.tokens) else "mismatch", ours, theirs.tokens)
    for name in PRESENCE_FIELDS:
        ours, theirs = chars.get(name) is not None, name in dump
        row(name + " (present)", "match" if ours == theirs else "mismatch", ours, theirs)
    ids_entry = dump.get("android.logicalMultiCamera.physicalIds")
    if ids_entry is not None or physical_ids:
        theirs = dumpsys_camera.decode_byte_string_list(ids_entry.tokens) if ids_entry else []
        ours = sorted(physical_ids or [])
        row("android.logicalMultiCamera.physicalIds", "match" if ours == sorted(theirs) else "mismatch",
            ours, theirs)
    return rows


def crosscheck(probe: dict, dumpsys_text: str) -> dict:
    dump = dumpsys_camera.parse(dumpsys_text)
    entries = {e["id"]: e for e in probe["cameras"]["entries"] if e.get("characteristics") is not None}
    report = {"cameras": {}, "only_in_probe": sorted(set(entries) - set(dump)),
              "only_in_dumpsys": sorted(set(dump) - set(entries))}
    for cam_id in sorted(set(entries) & set(dump)):
        e = entries[cam_id]
        report["cameras"][cam_id] = compare_camera(e["characteristics"], e.get("physical_ids"), dump[cam_id])
    verdicts = [r["verdict"] for rows in report["cameras"].values() for r in rows]
    report["matches"] = verdicts.count("match")
    report["mismatches"] = verdicts.count("mismatch")
    if report["mismatches"]:
        report["verdict"] = "fail"
    elif report["matches"] >= MIN_MATCHES:
        report["verdict"] = "pass"
    else:
        report["verdict"] = "could_not_tell"
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("probe_json", type=Path)
    ap.add_argument("dumpsys_txt", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="write the report as JSON here")
    args = ap.parse_args(argv)
    if not args.probe_json.is_file() or not args.dumpsys_txt.is_file():
        print("probe JSON or dumpsys file not found", file=sys.stderr)
        return 2
    probe = json.loads(args.probe_json.read_text(encoding="utf-8"))
    report = crosscheck(probe, args.dumpsys_txt.read_text(encoding="utf-8", errors="replace"))
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return {"pass": 0, "fail": 1}.get(report["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
