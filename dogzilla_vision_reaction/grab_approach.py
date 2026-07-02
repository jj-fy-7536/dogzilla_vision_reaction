from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .types import Detection


class GrabRobot(Protocol):
    def forward(self, speed: int = 8, seconds: float = 0.5) -> None: ...

    def backward(self, speed: int = 8, seconds: float = 0.5) -> None: ...

    def left(self, speed: int = 8, seconds: float = 0.5) -> None: ...

    def right(self, speed: int = 8, seconds: float = 0.5) -> None: ...

    def grab(
        self,
        open_claw: int = 5,
        close_claw: int = 245,
        reach_radius: int = 200,
        reach_height: int = 130,
        lift_radius: int = 90,
        lift_height: int = 100,
    ) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class GrabApproachConfig:
    center_tolerance_px: int = 45
    ready_area_ratio: float = 0.025
    too_close_area_ratio: float = 0.09


@dataclass(frozen=True)
class GrabApproachDecision:
    action: str
    reason: str
    target_center_x: float | None = None
    target_area_ratio: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "reason": self.reason,
            "target_center_x": round(self.target_center_x, 2) if self.target_center_x is not None else None,
            "target_area_ratio": round(self.target_area_ratio, 6) if self.target_area_ratio is not None else None,
        }


def decide_grab_step(
    detection: Detection | None,
    image_width: int,
    config: GrabApproachConfig,
) -> GrabApproachDecision:
    if detection is None or detection.bbox is None:
        return GrabApproachDecision(action="stop", reason="target_not_found")

    center_x = detection.bbox.x + detection.bbox.width / 2
    image_center_x = image_width / 2
    area_ratio = detection.area_ratio

    if area_ratio > config.too_close_area_ratio:
        return GrabApproachDecision(
            action="backward",
            reason="target_too_close",
            target_center_x=center_x,
            target_area_ratio=area_ratio,
        )

    if area_ratio < config.ready_area_ratio:
        return GrabApproachDecision(
            action="forward",
            reason="target_too_far",
            target_center_x=center_x,
            target_area_ratio=area_ratio,
        )

    if center_x < image_center_x - config.center_tolerance_px:
        return GrabApproachDecision(
            action="left",
            reason="target_left_of_center",
            target_center_x=center_x,
            target_area_ratio=area_ratio,
        )

    if center_x > image_center_x + config.center_tolerance_px:
        return GrabApproachDecision(
            action="right",
            reason="target_right_of_center",
            target_center_x=center_x,
            target_area_ratio=area_ratio,
        )

    return GrabApproachDecision(
        action="grab",
        reason="target_in_grab_range",
        target_center_x=center_x,
        target_area_ratio=area_ratio,
    )


def best_target_detection(detections: list[Detection], target_label: str = "red_target") -> Detection | None:
    matching = [detection for detection in detections if detection.label == target_label]
    if not matching:
        return None
    return max(matching, key=lambda detection: detection.confidence)


def select_grab_target(
    detections: list[Detection],
    confidence_threshold: float,
    target_label: str = "red_target",
) -> Detection | None:
    target = best_target_detection(detections, target_label=target_label)
    if target is None or target.confidence < confidence_threshold:
        return None
    return target


def execute_grab_decision(
    robot: GrabRobot,
    decision: GrabApproachDecision,
    approach_speed: int,
    approach_seconds: float,
    align_speed: int,
    align_seconds: float,
    open_claw: int = 5,
    close_claw: int = 245,
    reach_radius: int = 200,
    reach_height: int = 130,
    lift_radius: int = 90,
    lift_height: int = 100,
) -> None:
    if decision.action == "forward":
        robot.forward(speed=approach_speed, seconds=approach_seconds)
    elif decision.action == "backward":
        robot.backward(speed=approach_speed, seconds=approach_seconds)
    elif decision.action == "left":
        robot.left(speed=align_speed, seconds=align_seconds)
    elif decision.action == "right":
        robot.right(speed=align_speed, seconds=align_seconds)
    elif decision.action == "grab":
        robot.grab(
            open_claw=open_claw,
            close_claw=close_claw,
            reach_radius=reach_radius,
            reach_height=reach_height,
            lift_radius=lift_radius,
            lift_height=lift_height,
        )
    else:
        robot.stop()
