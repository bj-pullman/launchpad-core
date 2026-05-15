from datetime import datetime, timezone

from modules.core.settings.settings_db import get_connection


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_job_runs_db():
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS scheduled_job_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            run_date TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NULL,
            finished_at TEXT NULL,
            error TEXT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(job_id, run_date)
        );

        CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_job_date
        ON scheduled_job_runs(job_id, run_date);
        """)
        conn.commit()


def has_successful_run(job_id: str, run_date: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM scheduled_job_runs
            WHERE job_id = ?
              AND run_date = ?
              AND status = 'success'
            """,
            (job_id, run_date),
        ).fetchone()

    return row is not None


def mark_job_started(job_id: str, run_date: str):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO scheduled_job_runs (
                job_id, run_date, status, started_at, finished_at,
                error, created_at, updated_at
            )
            VALUES (?, ?, 'running', ?, NULL, NULL, ?, ?)
            ON CONFLICT(job_id, run_date)
            DO UPDATE SET
                status = 'running',
                started_at = excluded.started_at,
                finished_at = NULL,
                error = NULL,
                updated_at = excluded.updated_at
            """,
            (job_id, run_date, now, now, now),
        )
        conn.commit()


def mark_job_finished(job_id: str, run_date: str):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE scheduled_job_runs
            SET status = 'success',
                finished_at = ?,
                error = NULL,
                updated_at = ?
            WHERE job_id = ?
              AND run_date = ?
            """,
            (now, now, job_id, run_date),
        )
        conn.commit()


def mark_job_failed(job_id: str, run_date: str, error: str):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE scheduled_job_runs
            SET status = 'failed',
                finished_at = ?,
                error = ?,
                updated_at = ?
            WHERE job_id = ?
              AND run_date = ?
            """,
            (now, error[:2000], now, job_id, run_date),
        )
        conn.commit()