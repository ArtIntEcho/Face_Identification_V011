from pathlib import Path

from fastapi.testclient import TestClient

from face_access.config import Settings
from face_access.main import create_app


def _logged_in_client(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(Settings(data_dir=tmp_path)))
    client.__enter__()
    client.post(
        "/api/auth/bootstrap",
        json={"username": "owner", "password": "correct horse battery staple"},
    )
    client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "correct horse battery staple"},
    )
    return client


def test_person_lifecycle_is_admin_only_and_uses_soft_delete(tmp_path: Path) -> None:
    anonymous = TestClient(create_app(Settings(data_dir=tmp_path / "anonymous")))
    with anonymous:
        assert anonymous.get("/api/people").status_code == 401

    client = _logged_in_client(tmp_path / "authorized")
    try:
        created = client.post(
            "/api/people",
            json={
                "person_id": "EMP-001",
                "name": "Test User",
                "department": "Operations",
                "position": "Engineer",
                "operation_level": "B",
            },
        )
        duplicate = client.post(
            "/api/people",
            json={"person_id": "EMP-001", "name": "Other", "operation_level": "C"},
        )
        inactive = client.patch("/api/people/EMP-001", json={"status": "inactive"})
        deleted = client.delete("/api/people/EMP-001")
        people = client.get("/api/people")
        reused = client.post(
            "/api/people",
            json={"person_id": "EMP-001", "name": "Replacement", "operation_level": "D"},
        )
    finally:
        client.__exit__(None, None, None)

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert inactive.json()["status"] == "inactive"
    assert deleted.status_code == 204
    assert people.json() == []
    assert reused.status_code == 409