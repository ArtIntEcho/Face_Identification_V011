from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from face_access.camera import CameraManager, CameraStatus
from face_access.config import Settings
from face_access.liveness import TurnDirection
from face_access.main import create_app
from face_access.model_backends import FaceDetection
from face_access.motion import FaceMotion


class FakeCapture:
    def __init__(self) -> None:
        self.released = False

    def isOpened(self) -> bool:
        return True

    def set(self, prop: int, value: float) -> bool:
        return True

    def read(self) -> tuple[bool, np.ndarray]:
        return True, np.zeros((48, 64, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released = True


class StubCameraManager:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def status(self) -> CameraStatus:
        return CameraStatus(True, True, "/dev/video0", 640, 480, None)

    def read_jpeg(self, timeout_seconds: float = 2.0) -> bytes:
        return b"server-frame"

    def mjpeg_frames(self) -> Iterator[bytes]:
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nserver-frame\r\n"


class FakeBackend:
    name = "fake"
    version = "server-camera-test"
    available = True

    def detect_faces(self, image: bytes) -> list[FaceDetection]:
        assert image == b"server-frame"
        return [FaceDetection(0, 0, 20, 20, 0.99)]

    def extract_embedding(self, image: bytes, face: FaceDetection) -> list[float]:
        return [1.0, 0.0, 0.0]

    def passive_liveness_score(self, image: bytes, face: FaceDetection) -> float:
        return 0.95


class FakeMotionAnalyzer:
    eye_open = False
    direction: TurnDirection | None = None

    def analyze(self, image: bytes) -> FaceMotion:
        return FaceMotion(0.25 if self.eye_open else 0.10, self.direction)

    def close(self) -> None:
        pass


def test_camera_manager_captures_jpeg_and_releases_device() -> None:
    capture = FakeCapture()
    manager = CameraManager(capture_factory=lambda *args: capture)

    manager.start()
    image = manager.read_jpeg()
    manager.stop()

    decoded = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (48, 64, 3)
    assert capture.released is True


def test_server_camera_mode_authenticates_without_uploaded_frames(tmp_path: Path) -> None:
    camera = StubCameraManager()
    analyzer = FakeMotionAnalyzer()
    app = create_app(
        Settings(data_dir=tmp_path, camera_mode="server"),
        FakeBackend(),
        analyzer,
        camera,  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        client.post(
            "/api/auth/bootstrap",
            json={"username": "owner", "password": "long secure password"},
        )
        client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "long secure password"},
        )
        client.post(
            "/api/people",
            json={"person_id": "EDGE-1", "name": "Edge", "operation_level": "A"},
        )
        client.post(
            "/api/people/EDGE-1/faces",
            files={"files": ("face.jpg", b"server-frame", "image/jpeg")},
        )
        health = client.get("/api/health").json()
        frame = client.get("/api/camera/frame")
        challenge = client.post("/api/authentication/challenges").json()
        first = client.post(
            f"/api/authentication/challenges/{challenge['challenge_id']}/frames"
        ).json()
        analyzer.eye_open = True
        blink = client.post(
            f"/api/authentication/challenges/{challenge['challenge_id']}/frames"
        ).json()
        analyzer.direction = TurnDirection(blink["required_action"])
        client.post(f"/api/authentication/challenges/{challenge['challenge_id']}/frames")
        final = client.post(
            f"/api/authentication/challenges/{challenge['challenge_id']}/frames"
        ).json()

    assert camera.started is True
    assert camera.stopped is True
    assert health["camera_mode"] == "server"
    assert health["camera_available"] is True
    assert frame.content == b"server-frame"
    assert first["status"] == "waiting_for_blink"
    assert blink["status"] == "waiting_for_action"
    assert final["status"] == "accepted"
    assert final["person_id"] == "EDGE-1"
