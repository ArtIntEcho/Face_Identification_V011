from pathlib import Path

from fastapi.testclient import TestClient

from face_access.config import Settings
from face_access.main import create_app


def test_bootstrap_and_login_flow(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        bootstrap = client.post(
            "/api/auth/bootstrap",
            json={"username": "owner", "password": "correct horse battery staple"},
        )
        duplicate = client.post(
            "/api/auth/bootstrap",
            json={"username": "other", "password": "another secure password"},
        )
        rejected = client.post(
            "/api/auth/login", json={"username": "owner", "password": "wrong password"}
        )
        accepted = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "correct horse battery staple"},
        )
        current = client.get("/api/auth/me")

    assert bootstrap.status_code == 201
    assert duplicate.status_code == 409
    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert current.json() == {
        "username": "owner",
        "person_id": None,
        "role": "admin",
        "operation_level": "A",
    }