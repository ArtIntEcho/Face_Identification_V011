from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from threading import Condition, Event, Thread
from time import monotonic

import cv2


class CameraUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CameraStatus:
    running: bool
    frame_available: bool
    device: str
    width: int | None
    height: int | None
    error: str | None


class CameraManager:
    def __init__(
        self,
        device: str = "/dev/video0",
        width: int = 1280,
        height: int = 720,
        fps: int = 15,
        capture_factory: Callable[..., cv2.VideoCapture] = cv2.VideoCapture,
    ) -> None:
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self._capture_factory = capture_factory
        self._condition = Condition()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._latest_jpeg: bytes | None = None
        self._frame_width: int | None = None
        self._frame_height: int | None = None
        self._sequence = 0
        self._error: str | None = None

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="face-access-camera", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        self._thread = None

    def status(self) -> CameraStatus:
        with self._condition:
            return CameraStatus(
                running=self._thread is not None and self._thread.is_alive(),
                frame_available=self._latest_jpeg is not None,
                device=self.device,
                width=self._frame_width,
                height=self._frame_height,
                error=self._error,
            )

    def read_jpeg(self, timeout_seconds: float = 2.0) -> bytes:
        deadline = monotonic() + timeout_seconds
        with self._condition:
            while self._latest_jpeg is None and not self._stop_event.is_set():
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            if self._latest_jpeg is None:
                raise CameraUnavailableError(self._error or "Camera frame is not available")
            return self._latest_jpeg

    def mjpeg_frames(self) -> Iterator[bytes]:
        last_sequence = -1
        while not self._stop_event.is_set():
            with self._condition:
                self._condition.wait_for(
                    lambda: self._sequence != last_sequence or self._stop_event.is_set(),
                    timeout=2.0,
                )
                if self._stop_event.is_set():
                    return
                frame = self._latest_jpeg
                last_sequence = self._sequence
            if frame is not None:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

    def _run(self) -> None:
        while not self._stop_event.is_set():
            capture = self._open_capture()
            if not capture.isOpened():
                self._set_error(f"Unable to open camera device {self.device}")
                capture.release()
                self._stop_event.wait(1.0)
                continue
            self._set_error(None)
            try:
                while not self._stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        self._set_error(f"Unable to read from camera device {self.device}")
                        break
                    encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
                    if not encoded:
                        self._set_error("Unable to encode camera frame")
                        continue
                    height, width = frame.shape[:2]
                    with self._condition:
                        self._latest_jpeg = jpeg.tobytes()
                        self._frame_width = int(width)
                        self._frame_height = int(height)
                        self._sequence += 1
                        self._error = None
                        self._condition.notify_all()
            finally:
                capture.release()
            self._stop_event.wait(0.25)

    def _open_capture(self) -> cv2.VideoCapture:
        source: str | int = int(self.device) if self.device.isdigit() else self.device
        capture = self._capture_factory(source, cv2.CAP_V4L2)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        return capture

    def _set_error(self, message: str | None) -> None:
        with self._condition:
            self._error = message
            self._condition.notify_all()
