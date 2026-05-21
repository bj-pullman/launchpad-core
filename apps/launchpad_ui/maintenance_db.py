import json
import sqlite3
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "instance" / "maintenance" / "data"
MAINTENANCE_DB_PATH = DATA_DIR / "system_maintenance.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(MAINTENANCE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_system_maintenance_db():
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS maintenance_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_key TEXT NOT NULL UNIQUE,
                timestamp TEXT NOT NULL,
                reason TEXT NULL,
                status TEXT NOT NULL DEFAULT 'unknown',
                backup_path TEXT NOT NULL,
                backup_root TEXT NULL,
                app_root TEXT NULL,
                source_version TEXT NULL,
                database_count INTEGER NOT NULL DEFAULT 0,
                protected_file_count INTEGER NOT NULL DEFAULT 0,
                include_app_snapshot INTEGER NOT NULL DEFAULT 0,
                app_snapshot_path TEXT NULL,
                errors_json TEXT NULL,
                metadata_json TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_maintenance_backups_timestamp
            ON maintenance_backups(timestamp);

            CREATE INDEX IF NOT EXISTS idx_maintenance_backups_status
            ON maintenance_backups(status);
            """
        )
        conn.commit()


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def _json(value):
    return json.dumps(value or [], ensure_ascii=False)


def upsert_backup_metadata(metadata: dict):
    init_system_maintenance_db()

    backup_path = metadata.get("backup_path") or ""
    timestamp = metadata.get("timestamp") or Path(backup_path).name
    backup_key = backup_path or timestamp

    status = "ok" if metadata.get("ok") else "issue"
    git_info = metadata.get("git") or {}

    source_version = (
        metadata.get("source_version")
        or metadata.get("version")
        or (git_info.get("commit") or "")[:12]
        or None
    )

    databases = metadata.get("databases") or []
    protected_files = metadata.get("protected_files") or []
    errors = metadata.get("errors") or []

    now = _now()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO maintenance_backups (
                backup_key,
                timestamp,
                reason,
                status,
                backup_path,
                backup_root,
                app_root,
                source_version,
                database_count,
                protected_file_count,
                include_app_snapshot,
                app_snapshot_path,
                errors_json,
                metadata_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(backup_key) DO UPDATE SET
                timestamp = excluded.timestamp,
                reason = excluded.reason,
                status = excluded.status,
                backup_path = excluded.backup_path,
                backup_root = excluded.backup_root,
                app_root = excluded.app_root,
                source_version = excluded.source_version,
                database_count = excluded.database_count,
                protected_file_count = excluded.protected_file_count,
                include_app_snapshot = excluded.include_app_snapshot,
                app_snapshot_path = excluded.app_snapshot_path,
                errors_json = excluded.errors_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                backup_key,
                timestamp,
                metadata.get("reason") or "unknown",
                status,
                backup_path,
                metadata.get("backup_root"),
                metadata.get("app_root"),
                source_version,
                len(databases),
                len(protected_files),
                1 if metadata.get("include_app_snapshot") else 0,
                metadata.get("app_snapshot"),
                _json(errors),
                json.dumps(metadata, ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()


def list_backup_records(limit: int = 20):
    init_system_maintenance_db()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM maintenance_backups
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    records = []

    for row in rows:
        item = dict(row)

        try:
            item["errors"] = json.loads(item.get("errors_json") or "[]")
        except Exception:
            item["errors"] = []

        item["ok"] = item.get("status") == "ok"
        item["display_path"] = item.get("backup_path") or ""
        records.append(item)

    return records