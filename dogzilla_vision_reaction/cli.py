from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

from .annotate import annotate_image
from .reaction_policy import ReactionConfig, choose_reaction
from .red_detector import RedTargetDetector
from .robot import DogzillaRobot, DryRunRobot


def run_image(args: argparse.Namespace) -> int:
    return analyze_and_react(args.image, args)


def run_camera(args: argparse.Namespace) -> int:
    capture_path = args.capture_output
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    capture_camera_frame(capture_path, warmup_seconds=args.camera_warmup)
    return analyze_and_react(capture_path, args)


def analyze_and_react(image_path: Path, args: argparse.Namespace) -> int:
    detector = RedTargetDetector(min_area_ratio=args.min_area_ratio)
    detections = detector.detect(image_path)
    reaction = choose_reaction(
        detections,
        ReactionConfig(
            action=args.action,
            confidence_threshold=args.confidence_threshold,
        ),
    )

    robot = build_robot(args)
    install_sigint_stop(robot)

    try:
        execute_reaction(robot, reaction.action, args)
    finally:
        if reaction.action == "none":
            robot.stop()

    if args.annotated:
        annotate_image(image_path, detections, args.annotated)

    payload = {
        "mode": "live" if args.live else "dry-run",
        "image_path": str(image_path),
        "detections": [detection.to_dict() for detection in detections],
        "reaction": reaction.to_dict(),
        "robot_events": getattr(robot, "events", []),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 0


def build_robot(args: argparse.Namespace) -> DryRunRobot | DogzillaRobot:
    if args.live:
        return DogzillaRobot(crouch_action_id=args.crouch_action_id)
    return DryRunRobot()


def execute_reaction(robot: DryRunRobot | DogzillaRobot, action: str, args: argparse.Namespace) -> None:
    if action == "forward":
        robot.forward(speed=args.forward_speed, seconds=args.seconds)
    elif action == "crouch":
        robot.crouch(height_delta=args.crouch_height, seconds=args.seconds)


def install_sigint_stop(robot: DryRunRobot | DogzillaRobot) -> None:
    previous_handler = signal.getsignal(signal.SIGINT)

    def handler(signum: int, frame: object) -> None:
        robot.stop()
        if callable(previous_handler):
            previous_handler(signum, frame)
        else:
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handler)


def capture_camera_frame(output_path: Path, warmup_seconds: float = 1.0) -> None:
    try:
        from picamera2 import Picamera2
    except ImportError as exc:  # pragma: no cover - robot-only dependency
        raise RuntimeError("Picamera2 is not installed. Run camera mode on the DOGZILLA Raspberry Pi.") from exc

    camera = Picamera2()
    try:
        config = camera.create_still_configuration(main={"size": (640, 480)})
        camera.configure(config)
        camera.start()
        time.sleep(warmup_seconds)
        camera.capture_file(str(output_path))
    finally:
        camera.stop()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--action", choices=("forward", "crouch"), default="forward")
    parser.add_argument("--min-area-ratio", type=float, default=0.01)
    parser.add_argument("--confidence-threshold", type=float, default=0.50)
    parser.add_argument("--live", action="store_true", help="control the real robot instead of dry-run")
    parser.add_argument("--forward-speed", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--crouch-height", type=int, default=15)
    parser.add_argument("--crouch-action-id", type=int)
    parser.add_argument("--annotated", type=Path)
    parser.add_argument("--json", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DOGZILLA-LITE red-target vision reaction")
    subparsers = parser.add_subparsers(dest="command", required=True)

    image = subparsers.add_parser("image", help="analyze one existing image")
    image.add_argument("--image", type=Path, required=True)
    add_common_args(image)
    image.set_defaults(func=run_image)

    camera = subparsers.add_parser("camera", help="capture one camera frame, analyze it, then react")
    camera.add_argument("--capture-output", type=Path, default=Path("demo/camera_frame.jpg"))
    camera.add_argument("--camera-warmup", type=float, default=1.0)
    add_common_args(camera)
    camera.set_defaults(func=run_camera)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
