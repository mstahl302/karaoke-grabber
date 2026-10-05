#!/usr/bin/env python3
"""Render assets/icon.svg into assets/icon.icns (and a 1024 PNG preview).

Uses only tools that ship with macOS: `sips` rasterises the SVG (with
transparent corners and correct gradients; PyMuPDF turns gradients black
and Quick Look adds a white background) and resizes it, and `iconutil`
packs the .iconset into a .icns. Run from anywhere:

    python3 assets/make_icon.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SVG = HERE / "icon.svg"
ICONSET = HERE / "icon.iconset"
ICNS = HERE / "icon.icns"
PREVIEW = HERE / "icon-1024.png"

# (filename, pixel size) pairs iconutil expects
SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def sips(*args: str) -> None:
    subprocess.run(["sips", *args], check=True, capture_output=True)


def main() -> int:
    if shutil.which("sips") is None or shutil.which("iconutil") is None:
        print("make_icon: needs macOS (sips and iconutil)", file=sys.stderr)
        return 1
    sips("-s", "format", "png", "-z", "1024", "1024", str(SVG), "--out", str(PREVIEW))
    shutil.rmtree(ICONSET, ignore_errors=True)
    ICONSET.mkdir()
    for name, px in SIZES:
        sips("-z", str(px), str(px), str(PREVIEW), "--out", str(ICONSET / name))
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS)], check=True)
    shutil.rmtree(ICONSET)
    print(f"wrote {ICNS.relative_to(HERE.parent)} and {PREVIEW.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
