from pathlib import Path

from fastapi.testclient import TestClient

from face_access.config import Settings
from face_access.main import create_app
from face_access.model_backends import FaceDetection


class FakeBackend:
    name = "fake"
    version = "test-512"
    available = True

    def detect_faces(self, image: bytes) -> list[FaceDetection]:
        return [] if image == b"no-face" else [FaceDetection(0, 0, 10, 10, 0.99)]

    def extract_embedding(self, image: bytes, face: FaceDetection) -> list[float]:
        return [1.0, 0.0, 0.0]

    def passive_liveness_score(self, image: bytes, face: FaceDetection) -> float:
        return 1.0


def test_admin_can_enroll_valid_photos_and_get_per_file_failures(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path), FakeBackend())
    with TestClient(app) as client:
        client.post(
            "/api/auth/bootstrap",
            json={"username": "owner", "password": "correct horse battery staple"},
        )
        client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "correct horse battery staple"},
        )
        client.post(
            "/api/people",
            json={"person_id": "EMP-9", "name": "Nine", "operation_level": "B"},
        )
        response = client.post(
            "/api/people/EMP-9/faces",
            files=[
                ("files", ("valid.jpg", b"valid", "image/jpeg")),
                ("files", ("empty.jpg", b"no-face", "image/jpeg")),
            ],
        )

    assert response.status_code == 200
    assert response.json()["success_count"] == 1
    assert response.json()["failure_count"] == 1
    assert response.json()["failures"][0]["reason"] == "No face detected"
    assert len(list((tmp_path / "registrations" / "EMP-9").glob("*.jpg"))) == 1