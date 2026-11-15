"""The calibration board shown full-screen on a monitor (camera-calibration.md, screen amendment).

A screen is flat and streak-free, and its pixels are exact: the board is drawn with whole-pixel
squares and markers, shown 1:1 (no scaling), and checked by a screenshot of that monitor.

  make    PNG of the monitor's size plus a spec JSON in target_a4_v2_landscape.json's format
  show    full-screen, borderless, 1:1 on the monitor at --at X,Y (Esc closes)
  verify  screenshot of that monitor must equal the PNG exactly (exit 1 if not, 3 if no grab)

The board's metric size is not trusted from the EDID (whole centimetres): it is set from the
monitor's pixel pitch and cross-checked by Foad's ruler, and calibrate.py --board-mm takes the
measured width and height.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from make_target import board_object, default_spec  # noqa: E402

MARGIN_PX = 20


def board_image(screen_w: int, screen_h: int, square_px: int) -> tuple[np.ndarray, dict]:
    """White screen-sized uint8 image with the 10 x 8 board centred at whole-pixel positions;
    square_px must be a multiple of 10 (marker 0.7 x square = 7 cells of whole pixels)."""
    b = dict(default_spec()["board"])
    if square_px % 10:
        raise ValueError("square_px must be a multiple of 10 so marker cells are whole pixels")
    w, h = b["cols"] * square_px, b["rows"] * square_px
    if w + 2 * MARGIN_PX > screen_w or h + 2 * MARGIN_PX > screen_h:
        raise ValueError(f"board {w}x{h} px does not fit {screen_w}x{screen_h} with margins")
    board = board_object(b).generateImage((w, h), marginSize=0, borderBits=1)
    img = np.full((screen_h, screen_w), 255, np.uint8)
    x0, y0 = (screen_w - w) // 2, (screen_h - h) // 2
    img[y0:y0 + h, x0:x0 + w] = board
    return img, {"origin_px": [x0, y0], "square_px": square_px, "size_px": [w, h]}


def make(args) -> int:
    import cv2
    img, geo = board_image(args.width, args.height, args.square_px)
    out = Path(args.out)
    cv2.imwrite(str(out.with_suffix(".png")), img)
    b = dict(default_spec()["board"])
    b["square_mm"] = round(args.square_px * args.pitch_mm, 5)
    b["marker_mm"] = round(0.7 * b["square_mm"], 5)
    spec = {"name": out.stem, "kind": "screen", "board": b, "screen": {
        "width_px": args.width, "height_px": args.height, "pitch_mm_nominal": args.pitch_mm,
        "pitch_source": args.pitch_source, **geo},
        "note": "board mm = pixels x nominal pitch; calibrate.py --board-mm takes the ruler's width,height"}
    out.with_suffix(".json").write_text(json.dumps(spec, indent=2) + "\n")
    print(json.dumps({"png": str(out.with_suffix(".png")), "board_mm_nominal":
                      [b["cols"] * b["square_mm"], b["rows"] * b["square_mm"]]}))
    return 0


def dpi_aware() -> None:
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor: coordinates in real pixels
        except OSError:
            ctypes.windll.user32.SetProcessDPIAware()


def keep_display_on(on: bool) -> None:
    """While the board is shown, ask Windows not to blank the display for idleness (as a video
    player does): the monitor slept during a capture on 2026-11-15. It cannot wake a display that is
    already off and does nothing about a locked session."""
    if sys.platform == "win32":
        import ctypes
        es_continuous, es_display_required = 0x80000000, 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | (es_display_required if on else 0))


def show(args) -> int:
    import tkinter as tk
    dpi_aware()
    keep_display_on(True)
    x, y = (int(v) for v in args.at.split(","))
    root = tk.Tk()
    photo = tk.PhotoImage(file=str(args.png))
    root.overrideredirect(True)
    root.geometry(f"{photo.width()}x{photo.height()}+{x}+{y}")
    root.configure(background="white", cursor="none")
    tk.Label(root, image=photo, borderwidth=0, highlightthickness=0).place(x=0, y=0)
    root.attributes("-topmost", True)
    root.bind("<Escape>", lambda _e: root.destroy())
    if args.seconds:
        root.after(int(args.seconds * 1000), root.destroy)
    try:
        root.mainloop()
    finally:
        keep_display_on(False)
    return 0


def compare(shot: np.ndarray, ref: np.ndarray) -> dict:
    """Exact 1:1 check: same size and every pixel within 2 grey levels (colour management)."""
    if shot.shape != ref.shape:
        return {"ok": False, "reason": f"size {shot.shape[::-1]} vs {ref.shape[::-1]}"}
    diff = np.abs(shot.astype(int) - ref.astype(int))
    bad = int((diff > 2).sum())
    return {"ok": bad == 0, "pixels_off": bad, "max_diff": int(diff.max())}


def verify(args) -> int:
    import cv2
    dpi_aware()
    try:
        from PIL import ImageGrab
    except ImportError:
        print("could not tell: Pillow missing", file=sys.stderr)
        return 3
    ref = cv2.imread(str(args.png), cv2.IMREAD_GRAYSCALE)
    x, y = (int(v) for v in args.at.split(","))
    grab = ImageGrab.grab(bbox=(x, y, x + ref.shape[1], y + ref.shape[0]), all_screens=True).convert("L")
    result = compare(np.asarray(grab), ref)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--width", type=int, default=1920)
    m.add_argument("--height", type=int, default=1080)
    m.add_argument("--square-px", type=int, default=120)
    m.add_argument("--pitch-mm", type=float, required=True)
    m.add_argument("--pitch-source", default="unstated")
    m.add_argument("--out", required=True, help="path without extension; writes .png and .json")
    for name in ("show", "verify"):
        s = sub.add_parser(name)
        s.add_argument("png", type=Path)
        s.add_argument("--at", default="0,0", help="the monitor's top-left in desktop pixels, X,Y")
        if name == "show":
            s.add_argument("--seconds", type=float, default=0, help="close after this long (0: Esc only)")
    args = ap.parse_args(argv)
    try:
        return {"make": make, "show": show, "verify": verify}[args.cmd](args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
