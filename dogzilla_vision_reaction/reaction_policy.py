from __future__ import annotations

from dataclasses import dataclass

from .types import Detection, ReactionResult


VALID_ACTIONS = {"forward", "crouch"}


@dataclass(frozen=True)
class ReactionConfig:
    target_label: str = "red_target"
    confidence_threshold: float = 0.50
    action: str = "forward"

    def __post_init__(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"action must be one of {sorted(VALID_ACTIONS)}")
        if not 0 <= self.confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")


def choose_reaction(detections: list[Detection], config: ReactionConfig) -> ReactionResult:
    target_detections = [item for item in detections if item.label == config.target_label]
    if not target_detections:
        return ReactionResult(action="none", reason="target_not_found")

    best = max(target_detections, key=lambda item: item.confidence)
    if best.confidence < config.confidence_threshold:
        return ReactionResult(action="none", reason="below_threshold", detection=best)

    return ReactionResult(action=config.action, reason="target_detected", detection=best)
