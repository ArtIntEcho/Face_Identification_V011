from pathlib import Path
import json

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

    def __init__(self) -> None:
        self.embedding_calls = 0
        self.passive_liveness_calls = 0

    def detect_faces(self, image: bytes) -> list[FaceDetection]:
        return [FaceDetection(0, 0, 20, 20, 0.99)]

    def extract_embedding(self, image: bytes, face: FaceDetection) -> list[float]:
        self.embedding_calls += 1
        return [1.0, 0.0, 0.0]

    def passive_liveness_score(self, image: bytes, face: FaceDetection) -> float:
        self.passive_liveness_calls += 1
        return 0.95


class FakeMotionAnalyzer:
    eye_open = False
    direction: TurnDirection | None = None

    def analyze(self, image: bytes) -> FaceMotion:
        return FaceMotion(0.25 if self.eye_open else 0.10, self.direction)

    def close(self) -> None:
        pass


def test_active_and_passive_liveness_then_matching_accepts_person(tmp_path: Path) -> None:
    analyzer = FakeMotionAnalyzer()
    backend = FakeBackend()
    app = create_app(Settings(data_dir=tmp_path), backend, analyzer)
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
        enrollment_embedding_calls = backend.embedding_calls
        assert backend.passive_liveness_calls == 0
        assert enrollment_embedding_calls == 1
        analyzer.eye_open = True
        blink_result = client.post(
            f"/api/authentication/challenges/{challenge['challenge_id']}/frames",
            files={"frame": ("frame.jpg", b"frame", "image/jpeg")},
        )
        analyzer.direction = TurnDirection(blink_result.json()["required_action"])
        first_action = client.post(
            f"/api/authentication/challenges/{challenge['challenge_id']}/frames",
            files={"frame": ("frame.jpg", b"frame", "image/jpeg")},
        )
        final = client.post(
            f"/api/authentication/challenges/{challenge['challenge_id']}/frames",
            files={"frame": ("frame.jpg", b"frame", "image/jpeg")},
        )
        logs = client.get("/api/logs").json()

    assert blink_result.json()["status"] == "waiting_for_action"
    assert first_action.json()["status"] == "waiting_for_action"
    assert final.status_code == 200
    assert final.json()["status"] == "accepted"
    assert final.json()["person_id"] == "EMP-1"
    assert final.json()["pad_score"] == 0.95
    assert backend.passive_liveness_calls == 1
    assert backend.embedding_calls == enrollment_embedding_calls + 1
    assert final.json()["required_action"] in {"left", "right", "up", "down"}
    assert final.json()["face_detection"]["confidence"] == 0.99
    details = json.loads(logs[0]["stage_timings_json"])
    assert details["liveness_mode"] == "blink_and_random_head_action"
    assert details["required_action"] == final.json()["required_action"]
    assert details["observed_actions"] == [final.json()["required_action"]]
    assert details["matching_frame"] == "best_open_eye_pre_blink"
    assert "blink_ms" in details