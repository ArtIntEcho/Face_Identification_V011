from datetime import UTC, datetime, timedelta
from pathlib import Path

from face_access.database import Database
from face_access.retention import apply_retention


def _insert_log(database: Database, timestamp: datetime, snapshot: Path | None) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO authentication_logs
                (authenticated_at, result, duration_ms, model_backend, snapshot_path)
            VALUES (?, 'rejected', 100, 'test', ?)
            """,
            (timestamp.isoformat(), str(snapshot) if snapshot else None),
        )


def test_retention_deletes_snapshots_before_logs(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, tzinfo=UTC)
    database = Database(tmp_path / "database.sqlite3")
    database.initialize()
    recent_snapshot = tmp_path / "recent.jpg"
    expired_snapshot = tmp_path / "expired.jpg"
    recent_snapshot.write_bytes(b"recent")
    expired_snapshot.write_bytes(b"expired")
    _insert_log(database, now - timedelta(days=2), recent_snapshot)
    _insert_log(database, now - timedelta(days=20), expired_snapshot)
    _insert_log(database, now - timedelta(days=366), None)

    screenshot_count, log_count = apply_retention(database, now)

    assert (screenshot_count, log_count) == (1, 1)
    assert recent_snapshot.exists()
    assert not expired_snapshot.exists()
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT snapshot_deleted_at FROM authentication_logs ORDER BY authenticated_at"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["snapshot_deleted_at"] is not None
    assert rows[1]["snapshot_deleted_at"] is None