from __future__ import annotations

import io
import json
import math
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Protocol

from PIL import Image, ImageDraw

from .robot import DogzillaRobot, DryRunRobot


class MotionRobot(Protocol):
    events: list[dict[str, object]]

    def forward(self, speed: int = 8, seconds: float = 0.5) -> None: ...

    def backward(self, speed: int = 8, seconds: float = 0.5) -> None: ...

    def left(self, speed: int = 8, seconds: float = 0.5) -> None: ...

    def right(self, speed: int = 8, seconds: float = 0.5) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class HardwareCheckResult:
    name: str
    mode: str
    events: list[dict[str, object]]
    details: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "mode": self.mode,
            "events": self.events,
            "details": self.details or {},
        }


class DryRunAudioPlayer:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def play_tone(self, frequency_hz: int = 880, seconds: float = 0.35) -> dict[str, object]:
        event = {"action": "tone", "frequency_hz": frequency_hz, "seconds": seconds}
        self.events.append(event)
        return event

    def play_file(self, audio_file: Path) -> dict[str, object]:
        event = {"action": "play_file", "audio_file": str(audio_file)}
        self.events.append(event)
        return event


class SystemAudioPlayer:
    def __init__(self, player_command: str | None = None) -> None:
        self.player_command = player_command
        self.events: list[dict[str, object]] = []

    def play_tone(self, frequency_hz: int = 880, seconds: float = 0.35) -> dict[str, object]:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio_path = Path(tmp.name)
        write_tone_wav(audio_path, frequency_hz=frequency_hz, seconds=seconds)
        try:
            return self.play_file(audio_path)
        finally:
            audio_path.unlink(missing_ok=True)

    def play_file(self, audio_file: Path) -> dict[str, object]:
        command = self._resolve_player_command()
        args = build_audio_command(command, audio_file)
        subprocess.run(args, check=True)
        event = {"action": "play_file", "audio_file": str(audio_file), "player": command}
        self.events.append(event)
        return event

    def _resolve_player_command(self) -> str:
        if self.player_command:
            return self.player_command

        for command in ("aplay", "paplay", "ffplay", "afplay"):
            if shutil.which(command):
                return command

        raise RuntimeError("No audio player found. Install/use aplay, paplay, ffplay, or afplay.")


def build_audio_command(command: str, audio_file: Path) -> list[str]:
    if command == "ffplay":
        return [command, "-nodisp", "-autoexit", "-loglevel", "error", str(audio_file)]
    return [command, str(audio_file)]


def write_tone_wav(
    output_path: Path,
    frequency_hz: int = 880,
    seconds: float = 0.35,
    sample_rate: int = 44100,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_samples = max(1, int(sample_rate * seconds))
    amplitude = 12000

    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for index in range(total_samples):
            value = int(amplitude * math.sin(2 * math.pi * frequency_hz * index / sample_rate))
            wav.writeframes(struct.pack("<h", value))


def run_motion_check(
    robot: MotionRobot,
    speed: int = 8,
    seconds: float = 0.4,
    include_lateral: bool = False,
) -> HardwareCheckResult:
    robot.forward(speed=speed, seconds=seconds)
    robot.backward(speed=speed, seconds=seconds)
    if include_lateral:
        robot.left(speed=speed, seconds=seconds)
        robot.right(speed=speed, seconds=seconds)
    robot.stop()
    return HardwareCheckResult(name="motion", mode=mode_name(robot), events=robot.events)


def run_audio_check(
    player: DryRunAudioPlayer | SystemAudioPlayer,
    frequency_hz: int = 880,
    seconds: float = 0.35,
    audio_file: Path | None = None,
) -> HardwareCheckResult:
    if audio_file:
        player.play_file(audio_file)
    else:
        player.play_tone(frequency_hz=frequency_hz, seconds=seconds)
    return HardwareCheckResult(name="audio", mode=mode_name(player), events=player.events)


def build_stream_urls(host: str, port: int, robot_ip: str | None = None) -> dict[str, str]:
    bind_url = f"http://{host}:{port}"
    computer_host = robot_ip or ("127.0.0.1" if host in {"0.0.0.0", "::"} else host)
    computer_url = f"http://{computer_host}:{port}"
    return {"bind_url": bind_url, "computer_url": computer_url}


class FrameProvider(Protocol):
    def read_jpeg(self) -> bytes: ...

    def close(self) -> None: ...


class SyntheticFrameProvider:
    def __init__(self) -> None:
        self.index = 0

    def read_jpeg(self) -> bytes:
        self.index += 1
        image = Image.new("RGB", (640, 480), (245, 245, 245))
        draw = ImageDraw.Draw(image)
        draw.rectangle((210, 150, 430, 330), outline=(220, 20, 20), width=8)
        draw.text((230, 220), f"DOGZILLA test stream {self.index}", fill=(20, 20, 20))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    def close(self) -> None:
        return None


class Picamera2FrameProvider:
    def __init__(self, size: tuple[int, int] = (640, 480)) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as exc:  # pragma: no cover - robot-only dependency
            raise RuntimeError("Picamera2 is not installed. Run live stream on the DOGZILLA Raspberry Pi.") from exc

        self.camera = Picamera2()
        config = self.camera.create_still_configuration(main={"size": size})
        self.camera.configure(config)
        self.camera.start()
        time.sleep(0.8)

    def read_jpeg(self) -> bytes:
        buffer = io.BytesIO()
        self.camera.capture_file(buffer, format="jpeg")
        return buffer.getvalue()

    def close(self) -> None:
        self.camera.stop()


def create_mjpeg_handler(provider: FrameProvider, fps: float = 8.0) -> type[BaseHTTPRequestHandler]:
    delay_seconds = 1.0 / max(fps, 0.1)

    class MjpegHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path in {"/", "/index.html"}:
                self._write_index()
                return

            if self.path != "/stream.mjpg":
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()

            try:
                while True:
                    frame = provider.read_jpeg()
                    self.wfile.write(b"--FRAME\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    time.sleep(delay_seconds)
            except (BrokenPipeError, ConnectionResetError):
                return

        def log_message(self, format: str, *args: object) -> None:
            return None

        def _write_index(self) -> None:
            body = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>DOGZILLA Stream</title></head><body>"
                "<h1>DOGZILLA-LITE Camera Stream</h1>"
                "<img src='/stream.mjpg' style='max-width:100%;height:auto'>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return MjpegHandler


def serve_mjpeg_stream(
    host: str = "0.0.0.0",
    port: int = 8000,
    provider_factory: Callable[[], FrameProvider] = Picamera2FrameProvider,
    fps: float = 8.0,
) -> None:
    provider = provider_factory()
    server = ThreadingHTTPServer((host, port), create_mjpeg_handler(provider, fps=fps))
    try:
        server.serve_forever()
    finally:
        provider.close()
        server.server_close()


def make_robot(live: bool, crouch_action_id: int | None = None) -> DryRunRobot | DogzillaRobot:
    if live:
        return DogzillaRobot(crouch_action_id=crouch_action_id)
    return DryRunRobot()


def make_audio_player(live: bool, player_command: str | None = None) -> DryRunAudioPlayer | SystemAudioPlayer:
    if live:
        return SystemAudioPlayer(player_command=player_command)
    return DryRunAudioPlayer()


def mode_name(adapter: Any) -> str:
    return "dry-run" if adapter.__class__.__name__.startswith("DryRun") else "live"


def dumps_result(result: HardwareCheckResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
