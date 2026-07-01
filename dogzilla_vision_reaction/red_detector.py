from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

from .types import BoundingBox, Detection


class RedTargetDetector:
    """Detect a high-contrast red target without OpenCV."""

    def __init__(
        self,
        min_area_ratio: float = 0.01,
        min_red: int = 120,
        dominance_delta: int = 50,
        confidence_full_area_ratio: float = 0.18,
    ) -> None:
        if min_area_ratio < 0:
            raise ValueError("min_area_ratio must be non-negative")
        if confidence_full_area_ratio <= 0:
            raise ValueError("confidence_full_area_ratio must be positive")

        self.min_area_ratio = min_area_ratio
        self.min_red = min_red
        self.dominance_delta = dominance_delta
        self.confidence_full_area_ratio = confidence_full_area_ratio

    def detect(self, image_path: str | Path) -> list[Detection]:
        path = Path(image_path)
        image = Image.open(path).convert("RGB")
        return self.detect_image(image, image_path=str(path))

    def detect_image(self, image: Image.Image, image_path: str = "camera") -> list[Detection]:
        pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
        red = pixels[:, :, 0]
        green = pixels[:, :, 1]
        blue = pixels[:, :, 2]
        mask = (
            (red >= self.min_red)
            & ((red - green) >= self.dominance_delta)
            & ((red - blue) >= self.dominance_delta)
        )

        component = largest_component(mask)
        if component is None:
            return []

        bbox, area = component
        image_area = float(mask.shape[0] * mask.shape[1])
        area_ratio = area / image_area
        if area_ratio < self.min_area_ratio:
            return []

        confidence = min(1.0, area_ratio / self.confidence_full_area_ratio)
        return [
            Detection(
                label="red_target",
                confidence=confidence,
                bbox=bbox,
                area_ratio=area_ratio,
                image_path=image_path,
            )
        ]


def largest_component(mask: np.ndarray) -> tuple[BoundingBox, int] | None:
    if mask.ndim != 2:
        raise ValueError("mask must be 2-dimensional")

    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    best_bbox: BoundingBox | None = None
    best_area = 0

    for y in range(height):
        for x in range(width):
            if visited[y, x] or not mask[y, x]:
                continue
            bbox, area = flood_fill_component(mask, visited, x, y)
            if area > best_area:
                best_area = area
                best_bbox = bbox

    if best_bbox is None:
        return None
    return best_bbox, best_area


def flood_fill_component(
    mask: np.ndarray,
    visited: np.ndarray,
    start_x: int,
    start_y: int,
) -> tuple[BoundingBox, int]:
    height, width = mask.shape
    queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
    visited[start_y, start_x] = True
    min_x = max_x = start_x
    min_y = max_y = start_y
    area = 0

    while queue:
        x, y = queue.popleft()
        area += 1
        min_x = min(min_x, x)
        max_x = max(max_x, x)
        min_y = min(min_y, y)
        max_y = max(max_y, y)

        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue
            if visited[ny, nx] or not mask[ny, nx]:
                continue
            visited[ny, nx] = True
            queue.append((nx, ny))

    return BoundingBox(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1), area
