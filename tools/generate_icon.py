"""Export the approved PNG artwork as a multi-resolution Windows icon.

The image design lives in app_icon.png. This script only converts and resizes
the existing artwork; it does not redraw, recolor, or regenerate the design.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "app_icon.png")
    parser.add_argument("--output", type=Path, default=ROOT / "app_icon.ico")
    args = parser.parse_args()
    with Image.open(args.source) as original:
        if original.width != original.height or original.width < 256:
            raise ValueError("Use a square source image at least 256 px wide")
        artwork = original.convert("RGBA")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    artwork.save(args.output, format="ICO", sizes=[(size, size) for size in ICON_SIZES])
    with Image.open(args.output) as icon:
        actual = icon.ico.sizes()
        expected = {(size, size) for size in ICON_SIZES}
        if actual != expected:
            raise RuntimeError(f"Unexpected ICO resolutions: {actual}")
        for size in expected:
            icon.ico.getimage(size).load()
    print(f"{args.output}: {len(ICON_SIZES)} sizes ({', '.join(map(str, ICON_SIZES))} px)")


if __name__ == "__main__":
    main()
