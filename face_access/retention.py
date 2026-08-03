from datetime import UTC, datetime, timedelta
from pathlib import Path

from face_access.database import Database


def apply_retention(database: Database, now: datetime | None = None) -> tuple[int, int]:
    current_time = now or datetime.now(UTC)
    screenshot_cutoff = (current_time - timedelta(days=14)).isoformat()
    log_cutoff = (current_time - timedelta(days=365)).isoformat()
    deleted_screenshots = 0

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT id, snapshot_path FROM authentication_logs
            WHERE authenticated_at < ?
              AND snapshot_path IS NOT NULL
              AND snapshot_deleted_at IS NULL
            """,
            (screenshot_cutoff,),
        ).fetchall()
        for row in rows:
            Path(row["snapshot_path"]).unlink(missing_ok=True)
            connection.execute(
                "UPDATE authentication_logs SET snapshot_deleted_at = ? WHERE id = ?",
                (current_time.isoformat(), row["id"]),
            )
            deleted_screenshots += 1
        cursor = connection.execute(
            "DELETE FROM authentication_logs WHERE authenticated_at < ?", (log_cutoff,)
        )
    return deleted_screenshots, cursor.rowcount
