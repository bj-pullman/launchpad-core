from pathlib import Path
import sqlite3
from datetime import datetime
from config import settings

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

DB_PATH = settings.IMPORT_BY_SCAN_DB_PATH


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _format_timestamp_display(iso_str: str | None) -> str | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%m/%d/%Y %I:%M %p")
    except Exception:
        return iso_str


def _now_iso():
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo("America/Chicago")).isoformat(timespec="seconds")
        except Exception:
            pass
    return datetime.now().astimezone().isoformat(timespec="seconds")


def init_db():
    with _connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS import_by_scan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            profile_key TEXT NOT NULL,
            serial TEXT NOT NULL,
            ok INTEGER NOT NULL,
            asset_id INTEGER,
            asset_tag TEXT,
            asset_url TEXT,
            message TEXT
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_serial ON import_by_scan(serial)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_created_at ON import_by_scan(created_at)")


def log_scan(profile_key, serial, ok, asset_id=None, asset_tag=None, asset_url=None, message="") -> dict:
    init_db()
    created_at = _now_iso()

    with _connect() as conn:
        cur = conn.execute("""
            INSERT INTO import_by_scan
            (created_at, profile_key, serial, ok, asset_id, asset_tag, asset_url, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            created_at,
            profile_key,
            serial,
            1 if ok else 0,
            asset_id,
            asset_tag,
            asset_url,
            message
        ))
        row_id = cur.lastrowid

    return {
        "id": row_id,
        "created_at": created_at,
        "timestamp": created_at,
        "timestamp_display": _format_timestamp_display(created_at),
    }


def get_recent(limit=25):
    init_db()

    with _connect() as conn:
        rows = conn.execute("""
            SELECT id, created_at, profile_key, serial, ok,
                   asset_id, asset_tag, asset_url, message
            FROM import_by_scan
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        d["timestamp"] = d.get("created_at")
        d["timestamp_display"] = _format_timestamp_display(d.get("created_at"))
        out.append(d)

    return out