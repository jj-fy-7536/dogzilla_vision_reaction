from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

from .annotate import annotate_image
from .hardware_checks import (
    SyntheticFrameProvider,
    build_stream_urls,
    dumps_result,
    make_audio_player,
    make_robot,
    run_audio_check,
    run_motion_check,
    serve_mjpeg_stream,
)
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


def run_hardware_motion(args: argparse.Namespace) -> int:
    robot = make_robot(live=args.live, crouch_action_id=args.crouch_action_id)
    install_sigint_stop(robot)
    result = run_motion_check(
        robot,
        speed=args.speed,
        seconds=args.seconds,
        include_lateral=args.include_lateral,
    )
    print(dumps_result(result))
    return 0


def run_hardware_audio(args: argparse.Namespace) -> int:
    player = make_audio_player(live=args.live, player_command=args.player_command)
    result = run_audio_check(
        player,
        frequency_hz=args.frequency,
        seconds=args.seconds,
        audio_file=args.audio_file,
    )
    print(dumps_result(result))
    return 0


def run_hardware_stream(args: argparse.Namespace) -> int:
    urls = build_stream_urls(host=args.host, port=args.port, robot_ip=args.robot_ip)
    payload = {
        "name": "stream",
        "mode": "live" if args.live else "dry-run",
        "urls": urls,
        "stream_path": "/stream.mjpg",
        "message": "open computer_url in a browser on your computer",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)

    if not args.live:
        return 0

    provider_factory = SyntheticFrameProvider if args.test_pattern else None
    try:
        if provider_factory is None:
            serve_mjpeg_stream(host=args.host, port=args.port, fps=args.fps)
        else:
            serve_mjpeg_stream(host=args.host, port=args.port, provider_factory=provider_factory, fps=args.fps)
    except KeyboardInterrupt:
        return 0
    return 0


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

    hardware = subparsers.add_parser("hardware", help="run basic DOGZILLA-LITE hardware checks")
    hardware_subparsers = hardware.add_subparsers(dest="hardware_command", required=True)

    motion = hardware_subparsers.add_parser("motion", help="check forward/backward movement")
    motion.add_argument("--live", action="store_true", help="control the real robot instead of dry-run")
    motion.add_argument("--speed", type=int, default=8)
    motion.add_argument("--seconds", type=float, default=0.4)
    motion.add_argument("--include-lateral", action="store_true", help="also test left and right movement")
    motion.add_argument("--crouch-action-id", type=int)
    motion.set_defaults(func=run_hardware_motion)

    audio = hardware_subparsers.add_parser("audio", help="check speaker/audio output")
    audio.add_argument("--live", action="store_true", help="play through the robot/computer audio device")
    audio.add_argument("--frequency", type=int, default=880)
    audio.add_argument("--seconds", type=float, default=0.35)
    audio.add_argument("--audio-file", type=Path)
    audio.add_argument("--player-command", help="force a player command, such as aplay or ffplay")
    audio.set_defaults(func=run_hardware_audio)

    stream = hardware_subparsers.add_parser("stream", help="serve camera video to a computer browser")
    stream.add_argument("--live", action="store_true", help="start the HTTP MJPEG server")
    stream.add_argument("--host", default="0.0.0.0")
    stream.add_argument("--port", type=int, default=8000)
    stream.add_argument("--robot-ip", help="robot IP address shown in the computer URL")
    stream.add_argument("--fps", type=float, default=8.0)
    stream.add_argument("--test-pattern", action="store_true", help="stream a synthetic test image instead of Picamera2")
    stream.set_defaults(func=run_hardware_stream)

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
