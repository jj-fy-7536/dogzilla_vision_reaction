from __future__ import annotations

import importlib
import time
from typing import Any


class DryRunRobot:
    """Robot adapter used on a laptop. It records actions instead of moving."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def forward(self, speed: int = 8, seconds: float = 0.5) -> None:
        self.events.append({"action": "forward", "speed": speed, "seconds": seconds})

    def crouch(self, height_delta: int = 15, seconds: float = 0.5) -> None:
        self.events.append({"action": "crouch", "height_delta": height_delta, "seconds": seconds})

    def stop(self) -> None:
        self.events.append({"action": "stop"})


class DogzillaRobot:
    """Live DOGZILLA-LITE adapter.

    The forward action uses the documented DOGZILLA movement API:
    dog.move("x", value), then dog.move("x", 0).
    """

    def __init__(self, dog: Any | None = None, crouch_action_id: int | None = None) -> None:
        self.dog = dog if dog is not None else load_default_dog()
        self.crouch_action_id = crouch_action_id
        self.events: list[dict[str, object]] = []

    def forward(self, speed: int = 8, seconds: float = 0.5) -> None:
        self._call_if_exists("gait_type", "trot")
        self._call_if_exists("pace", "slow")
        self._require_call("move", "x", speed)
        self.events.append({"action": "forward", "speed": speed, "seconds": seconds})
        time.sleep(seconds)
        self.stop()

    def crouch(self, height_delta: int = 15, seconds: float = 0.5) -> None:
        if hasattr(self.dog, "translation"):
            self.dog.translation("z", -abs(height_delta))
            self.events.append({"action": "crouch", "height_delta": height_delta, "seconds": seconds})
            time.sleep(seconds)
            self.dog.translation("z", 0)
            return

        if self.crouch_action_id is not None and hasattr(self.dog, "action"):
            self.dog.action(self.crouch_action_id)
            self.events.append(
                {
                    "action": "crouch",
                    "height_delta": height_delta,
                    "seconds": seconds,
                    "action_id": self.crouch_action_id,
                }
            )
            time.sleep(seconds)
            return

        raise RuntimeError(
            "This DOGZILLA library does not expose translation('z', ...). "
            "Use --action forward first, or pass --crouch-action-id after checking the robot demos."
        )

    def stop(self) -> None:
        if hasattr(self.dog, "move"):
            self.dog.move("x", 0)
            self.dog.move("y", 0)
        elif hasattr(self.dog, "stop"):
            self.dog.stop()
        self.events.append({"action": "stop"})

    def _call_if_exists(self, method_name: str, *args: object) -> None:
        method = getattr(self.dog, method_name, None)
        if callable(method):
            method(*args)

    def _require_call(self, method_name: str, *args: object) -> None:
        method = getattr(self.dog, method_name, None)
        if not callable(method):
            raise RuntimeError(f"DOGZILLA object does not provide {method_name}()")
        method(*args)


def load_default_dog() -> Any:
    errors: list[str] = []

    try:
        module = importlib.import_module("uiutils")
        dog = getattr(module, "dog")
        return dog
    except Exception as exc:  # pragma: no cover - depends on robot image
        errors.append(f"uiutils.dog: {exc}")

    for module_name, class_name in (
        ("DOGZILLALib", "DOGZILLA"),
        ("DOGZILLALib.DOGZILLA", "DOGZILLA"),
    ):
        try:
            module = importlib.import_module(module_name)
            dog_class = getattr(module, class_name)
            return dog_class()
        except Exception as exc:  # pragma: no cover - depends on robot image
            errors.append(f"{module_name}.{class_name}: {exc}")

    detail = "; ".join(errors)
    raise RuntimeError(f"Could not load DOGZILLA robot library. Tried: {detail}")
