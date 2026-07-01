from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BoundingBox:
    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    bbox: BoundingBox | None
    area_ratio: float
    image_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "bbox": self.bbox.to_dict() if self.bbox else None,
            "area_ratio": round(self.area_ratio, 6),
            "image_path": self.image_path,
        }


@dataclass(frozen=True)
class ReactionResult:
    action: str
    reason: str
    detection: Detection | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "reason": self.reason,
            "detection": self.detection.to_dict() if self.detection else None,
        }
