from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

from PIL import Image

from .annotate import annotate_image
from .grab_approach import (
    GrabApproachConfig,
    decide_grab_step,
    execute_grab_decision,
    select_grab_target,
)
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
from .types import Detection


def run_image(args: argparse.Namespace) -> int:
    return analyze_and_react(args.image, args)


def run_camera(args: argparse.Namespace) -> int:
    if args.action == "grab" and args.live and args.grab_approach:
        return run_camera_grab_approach(args)

    capture_path = args.capture_output
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    capture_camera_frame(capture_path, warmup_seconds=args.camera_warmup)
    return analyze_and_react(capture_path, args)


def run_camera_grab_approach(args: argparse.Namespace) -> int:
    capture_path = args.capture_output
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    detector = build_detector(args)
    robot = build_robot(args)
    install_sigint_stop(robot)
    config = GrabApproachConfig(
        center_tolerance_px=args.grab_center_tolerance,
        ready_area_ratio=args.grab_ready_area_ratio,
        too_close_area_ratio=args.grab_too_close_area_ratio,
        ready_center_y_ratio=args.grab_ready_center_y_ratio,
        center_y_tolerance_ratio=args.grab_center_y_tolerance_ratio,
    )
    steps: list[dict[str, object]] = []
    detections = []
    final_decision = None

    for step_index in range(args.grab_max_steps):
        capture_camera_frame(capture_path, warmup_seconds=args.camera_warmup if step_index == 0 else 0.2)
        detections = detector.detect(capture_path)
        image_width, image_height = read_image_size(capture_path)
        target = select_grab_target(detections, confidence_threshold=args.confidence_threshold)
        decision = decide_grab_step(target, image_width=image_width, image_height=image_height, config=config)
        final_decision = decision
        step_payload = {
            "step": step_index + 1,
            "decision": decision.to_dict(),
            "detections": [detection.to_dict() for detection in detections],
        }
        steps.append(step_payload)

        if decision.action == "grab":
            execute_grab_decision_from_args(robot, decision, args)
            break
        execute_grab_decision_from_args(robot, decision, args)
        if decision.action == "stop":
            break

    if args.annotated:
        annotate_image(capture_path, detections, args.annotated)

    reaction_action = final_decision.action if final_decision else "none"
    reaction_reason = final_decision.reason if final_decision else "no_decision"
    payload = {
        "mode": "live",
        "image_path": str(capture_path),
        "detections": [detection.to_dict() for detection in detections],
        "reaction": {
            "action": reaction_action,
            "reason": reaction_reason,
            "grab_completed": reaction_action == "grab",
        },
        "approach_steps": steps,
        "robot_events": getattr(robot, "events", []),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 0


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
    detector = build_detector(args)
    detections = detector.detect(image_path)
    if args.action == "grab" and args.grab_approach:
        return analyze_and_approach_grab(image_path, detections, args)

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


def analyze_and_approach_grab(image_path: Path, detections: list[Detection], args: argparse.Namespace) -> int:
    target = select_grab_target(detections, confidence_threshold=args.confidence_threshold)
    image_width, image_height = read_image_size(image_path)
    decision = decide_grab_step(
        target,
        image_width=image_width,
        image_height=image_height,
        config=GrabApproachConfig(
            center_tolerance_px=args.grab_center_tolerance,
            ready_area_ratio=args.grab_ready_area_ratio,
            too_close_area_ratio=args.grab_too_close_area_ratio,
            ready_center_y_ratio=args.grab_ready_center_y_ratio,
            center_y_tolerance_ratio=args.grab_center_y_tolerance_ratio,
        ),
    )

    robot = build_robot(args)
    install_sigint_stop(robot)
    execute_grab_decision_from_args(robot, decision, args)

    if args.annotated:
        annotate_image(image_path, detections, args.annotated)

    payload = {
        "mode": "live" if args.live else "dry-run",
        "image_path": str(image_path),
        "detections": [detection.to_dict() for detection in detections],
        "reaction": {
            "action": decision.action,
            "reason": decision.reason,
            "grab_completed": decision.action == "grab",
        },
        "grab_approach_decision": decision.to_dict(),
        "robot_events": getattr(robot, "events", []),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 0


def execute_grab_decision_from_args(robot: DryRunRobot | DogzillaRobot, decision, args: argparse.Namespace) -> None:
    execute_grab_decision(
        robot,
        decision,
        approach_speed=args.grab_approach_speed,
        approach_seconds=args.grab_approach_seconds,
        align_speed=args.grab_align_speed,
        align_seconds=args.grab_align_seconds,
        open_claw=args.grab_open_claw,
        close_claw=args.grab_close_claw,
        reach_radius=args.grab_reach_radius,
        reach_height=args.grab_reach_height,
        lift_radius=args.grab_lift_radius,
        lift_height=args.grab_lift_height,
    )


def build_detector(args: argparse.Namespace) -> RedTargetDetector:
    return RedTargetDetector(
        min_area_ratio=args.min_area_ratio,
        min_red=args.min_red,
        dominance_delta=args.dominance_delta,
        confidence_full_area_ratio=args.confidence_full_area_ratio,
    )


def read_image_size(image_path: Path) -> tuple[int, int]:
    with Image.open(image_path) as image:
        return image.size


def build_robot(args: argparse.Namespace) -> DryRunRobot | DogzillaRobot:
    if args.live:
        return DogzillaRobot(crouch_action_id=args.crouch_action_id)
    return DryRunRobot()


def execute_reaction(robot: DryRunRobot | DogzillaRobot, action: str, args: argparse.Namespace) -> None:
    if action == "forward":
        robot.forward(speed=args.forward_speed, seconds=args.seconds)
    elif action == "crouch":
        robot.crouch(height_delta=args.crouch_height, seconds=args.seconds)
    elif action == "grab":
        robot.grab(
            open_claw=args.grab_open_claw,
            close_claw=args.grab_close_claw,
            reach_radius=args.grab_reach_radius,
            reach_height=args.grab_reach_height,
            lift_radius=args.grab_lift_radius,
            lift_height=args.grab_lift_height,
        )


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
        if hasattr(camera, "close"):
            camera.close()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--action", choices=("forward", "crouch", "grab"), default="forward")
    parser.add_argument("--min-area-ratio", type=float, default=0.003)
    parser.add_argument("--confidence-threshold", type=float, default=0.30)
    parser.add_argument("--min-red", type=int, default=100)
    parser.add_argument("--dominance-delta", type=int, default=25)
    parser.add_argument("--confidence-full-area-ratio", type=float, default=0.02)
    parser.add_argument("--live", action="store_true", help="control the real robot instead of dry-run")
    parser.add_argument("--forward-speed", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--crouch-height", type=int, default=15)
    parser.add_argument("--crouch-action-id", type=int)
    parser.add_argument("--grab-open-claw", type=int, default=5)
    parser.add_argument("--grab-close-claw", type=int, default=245)
    parser.add_argument("--grab-reach-radius", type=int, default=200)
    parser.add_argument("--grab-reach-height", type=int, default=130)
    parser.add_argument("--grab-lift-radius", type=int, default=90)
    parser.add_argument("--grab-lift-height", type=int, default=100)
    grab_approach_group = parser.add_mutually_exclusive_group()
    grab_approach_group.add_argument("--grab-approach", dest="grab_approach", action="store_true", default=True)
    grab_approach_group.add_argument("--no-grab-approach", dest="grab_approach", action="store_false")
    parser.add_argument("--grab-max-steps", type=int, default=12)
    parser.add_argument("--grab-center-tolerance", type=int, default=35)
    parser.add_argument("--grab-ready-area-ratio", type=float, default=0.025)
    parser.add_argument("--grab-too-close-area-ratio", type=float, default=0.09)
    parser.add_argument("--grab-ready-center-y-ratio", type=float, default=0.86)
    parser.add_argument("--grab-center-y-tolerance-ratio", type=float, default=0.02)
    parser.add_argument("--grab-approach-speed", type=int, default=10)
    parser.add_argument("--grab-approach-seconds", type=float, default=1.0)
    parser.add_argument("--grab-align-speed", type=int, default=6)
    parser.add_argument("--grab-align-seconds", type=float, default=0.7)
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
