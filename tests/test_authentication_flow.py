from pathlib import Path

from fastapi.testclient import TestClient

from face_access.config import Settings
from face_access.liveness import TurnDirection
from face_access.main import create_app
from face_access.model_backends import FaceDetection
from face_access.motion import FaceMotion


class FakeBackend:
    name = "fake"
    version = "fake-complete"
    available = True

    def detect_faces(self, image: bytes) -> list[FaceDetection]:
        return [FaceDetection(0, 0, 20, 20, 0.99)]

    def extract_embedding(self, image: bytes, face: FaceDetection) -> list[float]:
        return [1.0, 0.0, 0.0]

    def passive_liveness_score(self, image: bytes, face: FaceDetection) -> float:
        return 0.95


class FakeMotionAnalyzer:
    direction: TurnDirection | None = None
    eye_open = False

    def analyze(self, image: bytes) -> FaceMotion:
        return FaceMotion(0.25 if self.eye_open else 0.10, self.direction)

    def close(self) -> None:
        pass


def test_active_and_passive_liveness_then_matching_accepts_person(tmp_path: Path) -> None:
    analyzer = FakeMotionAnalyzer()
    app = create_app(Settings(data_dir=tmp_path), FakeBackend(), analyzer)
    with TestClient(app) as client:
        client.post("/api/auth/bootstrap", json={"username": "owner", "password": "long secure password"})
        client.post("/api/auth/login", json={"username": "owner", "password": "long secure password"})
        client.post(
            "/api/people",
            json={"person_id": "EMP-1", "name": "One", "operation_level": "A"},
        )
        client.post(
            "/api/people/EMP-1/faces",
            files={"files": ("face.jpg", b"face", "image/jpeg")},
        )
        challenge = client.post("/api/authentication/challenges").json()
        assert challenge["timeout_seconds"] == 15.0
        first = client.post(
            f"/api/authentication/challenges/{challenge['challenge_id']}/frames",
            files={"frame": ("frame.jpg", b"frame", "image/jpeg")},
        ).json()
        analyzer.eye_open = True
        analyzer.direction = TurnDirection(first["required_turn"])
        final = client.post(
            f"/api/authentication/challenges/{challenge['challenge_id']}/frames",
            files={"frame": ("frame.jpg", b"frame", "image/jpeg")},
        )

    assert final.status_code == 200
    assert final.json()["status"] == "accepted"
    assert final.json()["person_id"] == "EMP-1"
    assert final.json()["pad_score"] == 0.95