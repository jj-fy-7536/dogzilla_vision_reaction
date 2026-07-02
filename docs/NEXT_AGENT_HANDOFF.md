# DOGZILLA Vision Reaction Handoff

Date: 2026-07-02

## Current Goal

Continue real-world testing for the DOGZILLA-LITE red-ball vision reaction project. The target behavior is:

1. Detect the red ball.
2. Approach until the ball is in a usable grab range.
3. Align horizontally.
4. Trigger the mechanical arm grab.

## Repository State

- GitHub repo: `https://github.com/jj-fy-7536/dogzilla_vision_reaction`
- Local repo: `/Users/shanqicheng/Desktop/小车/dogzilla_vision_reaction`
- Robot project path: `/home/pi/dogzilla_vision_reaction`
- Robot SSH alias: `dogzilla-lite`
- Last pushed baseline before this handoff: `b1092ed Add distance-first grab approach`

This handoff commit adds a follow-up fix based on live testing: distance is now judged mainly by the red target's vertical center in the camera image, not by bounding-box area alone.

## What Was Learned From Real Testing

The robot connected successfully over SSH and could run the project on-board.

On the robot:

```bash
cd /home/pi/dogzilla_vision_reaction
python3 -m unittest discover -s tests
python3 -m compileall dogzilla_vision_reaction scripts tests
```

Both passed before live testing.

Initial dry-run saw the red ball:

- confidence around `0.59`
- bbox around `x=258, y=377, w=60, h=82`
- area ratio around `0.0118`
- decision: `forward`

First live approach used very small steps:

```bash
python3 -m dogzilla_vision_reaction.cli camera \
  --action grab \
  --live \
  --grab-max-steps 8 \
  --grab-approach-speed 5 \
  --grab-approach-seconds 0.25 \
  --grab-align-speed 4 \
  --grab-align-seconds 0.18 \
  --capture-output demo/live_grab_approach_frame.jpg \
  --annotated demo/live_grab_approach_annotated.jpg \
  --json demo/live_grab_approach_result.json
```

It sent 8 `forward` commands but the red-ball area barely changed. The cause was likely that `xgolib` has a default movement timing around `0.65s`, and `0.25s` was too short to produce meaningful displacement.

Diagnostic movement with `x=10` for `1.2s` did move the robot: the area ratio increased from roughly `0.0114` to `0.0142`.

Second live approach used larger steps:

```bash
python3 -m dogzilla_vision_reaction.cli camera \
  --action grab \
  --live \
  --grab-max-steps 5 \
  --grab-approach-speed 10 \
  --grab-approach-seconds 1.0 \
  --grab-align-speed 6 \
  --grab-align-seconds 0.7 \
  --grab-ready-area-ratio 0.018 \
  --capture-output demo/live_grab_tuned_frame.jpg \
  --annotated demo/live_grab_tuned_annotated.jpg \
  --json demo/live_grab_tuned_result.json
```

It moved closer, but the red ball dropped to the bottom of the frame and became partly clipped:

- step 1: `bbox x=242,y=388,w=67,h=92`, area `0.01457`
- step 2: `bbox x=237,y=413,w=77,h=67`, area `0.013861`
- step 3: `bbox x=226,y=439,w=82,h=41`, area `0.00821`
- step 4: target lost

This showed area ratio is unreliable near the bottom of the image because the ball gets clipped. The code now treats a low vertical center as close/too close.

## Current Code Change

Key file:

- `dogzilla_vision_reaction/grab_approach.py`

Current decision model:

- no target: `stop`
- target area too large, or target vertical center too low: `backward`
- target vertical center too high: `forward`
- target at usable vertical distance but left/right of center: lateral align
- target at usable distance and centered: `grab`

New defaults:

- `--grab-ready-center-y-ratio 0.86`
- `--grab-center-y-tolerance-ratio 0.02`
- `--grab-center-tolerance 35`
- `--grab-approach-speed 10`
- `--grab-approach-seconds 1.0`
- `--grab-align-speed 6`
- `--grab-align-seconds 0.7`

Regression test added for the live failure case:

- a target at `bbox=(226,439,82,41)` in a `640x480` frame must choose `backward`, not `forward`.

## Important Interruption Note

The final attempted command was interrupted by the user:

```bash
dog.move("x", -10)
time.sleep(1.0)
dog.stop()
```

It may have already executed a short backward recovery step before interruption. Do not assume the robot's current position. First run a camera dry-run to inspect the red ball position.

## Next Recommended Steps

1. Pull or sync the latest GitHub code onto the robot.
2. Put the red ball in view.
3. Run a dry-run camera check first:

```bash
cd /home/pi/dogzilla_vision_reaction
python3 -m dogzilla_vision_reaction.cli camera \
  --action grab \
  --capture-output demo/next_dryrun_frame.jpg \
  --annotated demo/next_dryrun_annotated.jpg \
  --json demo/next_dryrun_result.json
```

4. Inspect `reaction`:

- `backward`: robot is too close; let it back up in a controlled live run or manually reset position.
- `forward`: robot is still too far.
- `left`/`right`: distance is usable; horizontal alignment is next.
- `grab`: it should attempt the mechanical arm grab.

5. First live retry should be conservative:

```bash
python3 -m dogzilla_vision_reaction.cli camera \
  --action grab \
  --live \
  --grab-max-steps 4 \
  --capture-output demo/next_live_frame.jpg \
  --annotated demo/next_live_annotated.jpg \
  --json demo/next_live_result.json
```

6. If it oscillates between forward/backward, widen the vertical tolerance:

```bash
--grab-center-y-tolerance-ratio 0.04
```

7. If it grabs too early or too late, tune:

```bash
--grab-ready-center-y-ratio 0.84
--grab-ready-center-y-ratio 0.88
```

Lower means it grabs when the ball appears higher/farther; higher means it waits until the ball is lower/closer.

## Suggested Skills

- `superpowers:systematic-debugging`: Use for live robot behavior; avoid guessing from one failed run.
- `superpowers:test-driven-development`: Add regression tests before changing approach logic.
- `superpowers:verification-before-completion`: Run fresh tests before reporting completion or pushing.
