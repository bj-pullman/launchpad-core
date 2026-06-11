from pathlib import Path
import json
import sqlite3
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "instance" / "snipeops" / "secure_user_rostering"
DB_PATH = DATA_DIR / "secure_user_rostering.db"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_secure_user_rostering_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS secure_user_rostering_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            snipe_user_id INTEGER NULL,
            target_snipe_user_id INTEGER NULL,
            asset_count INTEGER NOT NULL DEFAULT 0,
            details_json TEXT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_secure_user_rostering_audit_action
        ON secure_user_rostering_audit(action);

        CREATE INDEX IF NOT EXISTS idx_secure_user_rostering_audit_created
        ON secure_user_rostering_audit(created_at);
        """)
        conn.commit()


def write_audit(
    *,
    action,
    status,
    snipe_user_id=None,
    target_snipe_user_id=None,
    asset_count=0,
    details=None,
):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO secure_user_rostering_audit (
                action,
                status,
                snipe_user_id,
                target_snipe_user_id,
                asset_count,
                details_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action,
                status,
                snipe_user_id,
                target_snipe_user_id,
                int(asset_count or 0),
                json.dumps(details or {}, default=str),
                utc_now_iso(),
            ),
        )
        conn.commit()