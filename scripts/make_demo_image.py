from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def make_demo_image(output: Path) -> None:
    image = Image.new("RGB", (320, 240), "white")
    for x in range(120, 205):
        for y in range(70, 155):
            image.putpixel((x, y), (235, 20, 20))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a demo red-target image")
    parser.add_argument("--output", type=Path, default=Path("demo/red_target.png"))
    args = parser.parse_args()
    make_demo_image(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
