from fastapi.testclient import TestClient

from face_access.config import Settings
from face_access.main import create_app


def test_health_reports_unavailable_model_backend() -> None:
    app = create_app(Settings(model_backend="unavailable"))
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model_backend": "unavailable",
        "model_backend_version": "none",
        "model_backend_available": False,
        "model_backend_error": None,
        "camera_mode": "browser",
        "camera_available": None,
        "camera_error": None,
    }