import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from dogzilla_vision_reaction.cli import build_parser
from dogzilla_vision_reaction.grab_approach import (
    GrabApproachConfig,
    decide_grab_step,
    execute_grab_decision,
    select_grab_target,
)
from dogzilla_vision_reaction.hardware_checks import (
    DryRunAudioPlayer,
    build_stream_urls,
    run_motion_check,
)
from dogzilla_vision_reaction.red_detector import RedTargetDetector
from dogzilla_vision_reaction.reaction_policy import ReactionConfig, choose_reaction
from dogzilla_vision_reaction.robot import DryRunRobot, load_default_dog
from dogzilla_vision_reaction.types import BoundingBox, Detection


class VisionReactionTests(unittest.TestCase):
    def test_red_detector_finds_red_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "red_target.png"
            image = Image.new("RGB", (160, 120), "white")
            for x in range(60, 105):
                for y in range(35, 80):
                    image.putpixel((x, y), (230, 20, 20))
            image.save(image_path)

            detections = RedTargetDetector(min_area_ratio=0.02).detect(image_path)

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].label, "red_target")
        self.assertEqual(detections[0].bbox, BoundingBox(x=60, y=35, width=45, height=45))
        self.assertGreater(detections[0].confidence, 0.5)

    def test_red_detector_defaults_find_small_camera_red_ball(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "camera_ball.jpg"
            image = Image.new("RGB", (640, 480), "white")
            for x in range(307, 352):
                for y in range(343, 404):
                    image.putpixel((x, y), (225, 35, 40))
            image.save(image_path)

            detections = RedTargetDetector().detect(image_path)

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].bbox, BoundingBox(x=307, y=343, width=45, height=61))
        self.assertGreater(detections[0].confidence, 0.3)

    def test_policy_triggers_forward_above_threshold(self):
        detection = Detection(
            label="red_target",
            confidence=0.72,
            bbox=BoundingBox(10, 20, 30, 40),
            area_ratio=0.08,
            image_path="frame.jpg",
        )

        result = choose_reaction([detection], ReactionConfig(action="forward", confidence_threshold=0.6))

        self.assertEqual(result.action, "forward")
        self.assertEqual(result.reason, "target_detected")
        self.assertEqual(result.detection, detection)

    def test_policy_can_trigger_grab_action(self):
        detection = Detection(
            label="red_target",
            confidence=0.72,
            bbox=BoundingBox(307, 343, 45, 61),
            area_ratio=0.0069,
            image_path="camera_ball.jpg",
        )

        result = choose_reaction([detection], ReactionConfig(action="grab"))

        self.assertEqual(result.action, "grab")
        self.assertEqual(result.reason, "target_detected")

    def test_grab_approach_moves_forward_when_target_is_small(self):
        detection = Detection(
            label="red_target",
            confidence=0.65,
            bbox=BoundingBox(300, 320, 45, 60),
            area_ratio=0.008,
            image_path="camera_ball.jpg",
        )

        decision = decide_grab_step(detection, image_width=640, image_height=480, config=GrabApproachConfig())

        self.assertEqual(decision.action, "forward")
        self.assertEqual(decision.reason, "target_too_far")

    def test_grab_approach_backs_up_when_target_is_low_and_partly_clipped(self):
        detection = Detection(
            label="red_target",
            confidence=0.65,
            bbox=BoundingBox(226, 439, 82, 41),
            area_ratio=0.00821,
            image_path="camera_ball.jpg",
        )

        decision = decide_grab_step(detection, image_width=640, image_height=480, config=GrabApproachConfig())

        self.assertEqual(decision.action, "backward")
        self.assertEqual(decision.reason, "target_too_close")

    def test_grab_approach_aligns_left_before_grabbing(self):
        detection = Detection(
            label="red_target",
            confidence=0.65,
            bbox=BoundingBox(249, 367, 60, 89),
            area_ratio=0.01319,
            image_path="camera_ball.jpg",
        )

        decision = decide_grab_step(detection, image_width=640, image_height=480, config=GrabApproachConfig())

        self.assertEqual(decision.action, "left")
        self.assertEqual(decision.reason, "target_left_of_center")

    def test_grab_approach_grabs_when_centered_and_close(self):
        detection = Detection(
            label="red_target",
            confidence=0.65,
            bbox=BoundingBox(290, 367, 60, 89),
            area_ratio=0.01319,
            image_path="camera_ball.jpg",
        )

        decision = decide_grab_step(detection, image_width=640, image_height=480, config=GrabApproachConfig())

        self.assertEqual(decision.action, "grab")
        self.assertEqual(decision.reason, "target_in_grab_range")

    def test_grab_approach_backs_up_when_target_is_too_close(self):
        detection = Detection(
            label="red_target",
            confidence=0.65,
            bbox=BoundingBox(230, 280, 190, 160),
            area_ratio=0.12,
            image_path="camera_ball.jpg",
        )

        decision = decide_grab_step(detection, image_width=640, image_height=480, config=GrabApproachConfig())

        self.assertEqual(decision.action, "backward")
        self.assertEqual(decision.reason, "target_too_close")

    def test_grab_approach_stops_when_target_is_missing(self):
        decision = decide_grab_step(None, image_width=640, image_height=480, config=GrabApproachConfig())

        self.assertEqual(decision.action, "stop")
        self.assertEqual(decision.reason, "target_not_found")

    def test_select_grab_target_ignores_low_confidence_target(self):
        detection = Detection(
            label="red_target",
            confidence=0.29,
            bbox=BoundingBox(290, 360, 80, 95),
            area_ratio=0.028,
            image_path="camera_ball.jpg",
        )

        target = select_grab_target([detection], confidence_threshold=0.30)

        self.assertIsNone(target)

    def test_select_grab_target_uses_highest_confidence_target(self):
        weak_detection = Detection(
            label="red_target",
            confidence=0.42,
            bbox=BoundingBox(290, 360, 80, 95),
            area_ratio=0.028,
            image_path="camera_ball.jpg",
        )
        strong_detection = Detection(
            label="red_target",
            confidence=0.78,
            bbox=BoundingBox(300, 350, 90, 105),
            area_ratio=0.031,
            image_path="camera_ball.jpg",
        )

        target = select_grab_target([weak_detection, strong_detection], confidence_threshold=0.30)

        self.assertEqual(target, strong_detection)

    def test_no_grab_approach_flag_disables_active_grab_approach(self):
        parser = build_parser()

        args = parser.parse_args(["image", "--image", "frame.jpg", "--action", "grab", "--no-grab-approach"])

        self.assertFalse(args.grab_approach)

    def test_execute_grab_decision_uses_forward_for_too_far_target(self):
        robot = DryRunRobot()
        detection = Detection(
            label="red_target",
            confidence=0.65,
            bbox=BoundingBox(300, 320, 45, 60),
            area_ratio=0.0126,
            image_path="camera_ball.jpg",
        )
        decision = decide_grab_step(detection, image_width=640, image_height=480, config=GrabApproachConfig())

        execute_grab_decision(
            robot,
            decision,
            approach_speed=6,
            approach_seconds=0.25,
            align_speed=5,
            align_seconds=0.2,
        )

        self.assertEqual(robot.events, [{"action": "forward", "speed": 6, "seconds": 0.25}])

    def test_policy_default_threshold_triggers_small_camera_target(self):
        detection = Detection(
            label="red_target",
            confidence=0.35,
            bbox=BoundingBox(307, 343, 45, 61),
            area_ratio=0.0069,
            image_path="camera_ball.jpg",
        )

        result = choose_reaction([detection], ReactionConfig(action="forward"))

        self.assertEqual(result.action, "forward")
        self.assertEqual(result.reason, "target_detected")

    def test_policy_does_not_move_below_threshold(self):
        detection = Detection(
            label="red_target",
            confidence=0.42,
            bbox=BoundingBox(10, 20, 30, 40),
            area_ratio=0.03,
            image_path="frame.jpg",
        )

        result = choose_reaction([detection], ReactionConfig(action="crouch", confidence_threshold=0.6))

        self.assertEqual(result.action, "none")
        self.assertEqual(result.reason, "below_threshold")

    def test_policy_ignores_non_target_label(self):
        detection = Detection(
            label="blue_target",
            confidence=0.99,
            bbox=BoundingBox(10, 20, 30, 40),
            area_ratio=0.12,
            image_path="frame.jpg",
        )

        result = choose_reaction([detection], ReactionConfig(target_label="red_target"))

        self.assertEqual(result.action, "none")
        self.assertEqual(result.reason, "target_not_found")

    def test_dry_run_robot_records_forward_and_crouch(self):
        robot = DryRunRobot()

        robot.forward(speed=12, seconds=0.1)
        robot.backward(speed=9, seconds=0.2)
        robot.crouch(height_delta=18, seconds=0.1)
        robot.grab(open_claw=5, close_claw=245, reach_radius=200, reach_height=130, lift_radius=90, lift_height=100)
        robot.stop()

        self.assertEqual(
            robot.events,
            [
                {"action": "forward", "speed": 12, "seconds": 0.1},
                {"action": "backward", "speed": 9, "seconds": 0.2},
                {"action": "crouch", "height_delta": 18, "seconds": 0.1},
                {
                    "action": "grab",
                    "open_claw": 5,
                    "close_claw": 245,
                    "reach_radius": 200,
                    "reach_height": 130,
                    "lift_radius": 90,
                    "lift_height": 100,
                },
                {"action": "stop"},
            ],
        )

    def test_load_default_dog_falls_back_to_xgolib(self):
        created: list[dict[str, object]] = []

        class FakeXGO:
            def __init__(self, port: str, version: str) -> None:
                created.append({"port": port, "version": version})

        def fake_import(name: str):
            if name == "xgolib":
                return SimpleNamespace(XGO=FakeXGO)
            raise ImportError(name)

        with patch("dogzilla_vision_reaction.robot.importlib.import_module", side_effect=fake_import):
            dog = load_default_dog()

        self.assertIsInstance(dog, FakeXGO)
        self.assertEqual(created, [{"port": "/dev/ttyAMA0", "version": "xgolite"}])

    def test_motion_check_runs_forward_and_backward(self):
        robot = DryRunRobot()

        result = run_motion_check(robot, speed=7, seconds=0.1, include_lateral=False)

        self.assertEqual(result.name, "motion")
        self.assertEqual(
            robot.events,
            [
                {"action": "forward", "speed": 7, "seconds": 0.1},
                {"action": "backward", "speed": 7, "seconds": 0.1},
                {"action": "stop"},
            ],
        )

    def test_motion_check_can_include_left_and_right(self):
        robot = DryRunRobot()

        run_motion_check(robot, speed=6, seconds=0.1, include_lateral=True)

        self.assertEqual(
            robot.events,
            [
                {"action": "forward", "speed": 6, "seconds": 0.1},
                {"action": "backward", "speed": 6, "seconds": 0.1},
                {"action": "left", "speed": 6, "seconds": 0.1},
                {"action": "right", "speed": 6, "seconds": 0.1},
                {"action": "stop"},
            ],
        )

    def test_dry_run_audio_records_tone(self):
        player = DryRunAudioPlayer()

        result = player.play_tone(frequency_hz=880, seconds=0.25)

        self.assertEqual(result, {"action": "tone", "frequency_hz": 880, "seconds": 0.25})
        self.assertEqual(player.events, [result])

    def test_stream_urls_use_robot_ip_for_computer_url(self):
        urls = build_stream_urls(host="0.0.0.0", port=8000, robot_ip="192.168.137.252")

        self.assertEqual(urls["bind_url"], "http://0.0.0.0:8000")
        self.assertEqual(urls["computer_url"], "http://192.168.137.252:8000")


if __name__ == "__main__":
    unittest.main()
