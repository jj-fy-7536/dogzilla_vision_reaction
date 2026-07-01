import tempfile
import unittest
from pathlib import Path

from PIL import Image

from dogzilla_vision_reaction.red_detector import RedTargetDetector
from dogzilla_vision_reaction.reaction_policy import ReactionConfig, choose_reaction
from dogzilla_vision_reaction.robot import DryRunRobot
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
        robot.crouch(height_delta=18, seconds=0.1)
        robot.stop()

        self.assertEqual(
            robot.events,
            [
                {"action": "forward", "speed": 12, "seconds": 0.1},
                {"action": "crouch", "height_delta": 18, "seconds": 0.1},
                {"action": "stop"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
