from modules.core.settings.settings_db import get_connection
from modules.core.utils.time import utc_now_iso


def start_sync_run(
    sync_key: str,
    source_system: str,
    target_system: str,
    trigger_type: str,
) -> int:
    now = utc_now_iso()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO sync_runs (
                sync_key,
                source_system,
                target_system,
                trigger_type,
                status,
                started_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sync_key,
                source_system,
                target_system,
                trigger_type,
                "running",
                now,
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def finish_sync_run(
    run_id: int,
    status: str,
    created_count: int = 0,
    updated_count: int = 0,
    unchanged_count: int = 0,
    skipped_count: int = 0,
    error_count: int = 0,
    message: str | None = None,
):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE sync_runs
            SET
                status = ?,
                finished_at = ?,
                created_count = ?,
                updated_count = ?,
                unchanged_count = ?,
                skipped_count = ?,
                error_count = ?,
                message = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                now,
                int(created_count),
                int(updated_count),
                int(unchanged_count),
                int(skipped_count),
                int(error_count),
                message,
                now,
                run_id,
            ),
        )
        conn.commit()


def list_recent_sync_runs(sync_key: str | None = None, limit: int = 20) -> list[dict]:
    params = []

    sql = """
        SELECT *
        FROM sync_runs
    """

    if sync_key:
        sql += " WHERE sync_key = ?"
        params.append(sync_key)

    sql += """
        ORDER BY started_at DESC
        LIMIT ?
    """
    params.append(int(limit))

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]