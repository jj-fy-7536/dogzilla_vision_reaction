from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .types import Detection


def annotate_image(image_path: str | Path, detections: list[Detection], output_path: str | Path) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    for detection in detections:
        if detection.bbox is None:
            continue
        bbox = detection.bbox
        x1 = bbox.x
        y1 = bbox.y
        x2 = bbox.x + bbox.width
        y2 = bbox.y + bbox.height
        draw.rectangle((x1, y1, x2, y2), outline=(255, 0, 0), width=3)
        draw.text((x1, max(0, y1 - 12)), f"{detection.label} {detection.confidence:.2f}", fill=(255, 0, 0))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
