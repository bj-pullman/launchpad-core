from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config.settings import SNIPE_CATALOG_DB_PATH
from modules.core.settings.settings_service import get_setting


DB_PATH = Path(SNIPE_CATALOG_DB_PATH).with_name("snipeops_checkout_assets.sqlite3")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _app_timezone() -> ZoneInfo:
    tz_name = (
        get_setting("general.timezone", "")
        or get_setting("app.timezone", "")
        or get_setting("timezone", "")
        or "America/Chicago"
    )

    try:
        return ZoneInfo(str(tz_name))
    except Exception:
        return ZoneInfo("America/Chicago")


def _format_timestamp(value: str | None) -> str:
    if not value:
        return ""

    raw = str(value).strip()

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        local_dt = dt.astimezone(_app_timezone())
        return local_dt.strftime("%m/%d/%Y %I:%M %p")
    except Exception:
        return raw


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS checkout_asset_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            parent_asset_id INTEGER,
            parent_asset_tag TEXT,
            parent_asset_name TEXT,
            child_asset_id INTEGER,
            child_asset_tag TEXT,
            child_asset_serial TEXT,
            child_asset_name TEXT,
            ok INTEGER NOT NULL DEFAULT 0,
            message TEXT
        )
        """)
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_checkout(
    *,
    parent_asset: dict | None,
    child_asset: dict | None,
    ok: bool,
    message: str,
) -> dict:
    init_db()

    created_at = _now_iso()

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO checkout_asset_logs(
                created_at,
                parent_asset_id,
                parent_asset_tag,
                parent_asset_name,
                child_asset_id,
                child_asset_tag,
                child_asset_serial,
                child_asset_name,
                ok,
                message
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                created_at,
                parent_asset.get("id") if parent_asset else None,
                parent_asset.get("asset_tag") if parent_asset else None,
                parent_asset.get("name") if parent_asset else None,
                child_asset.get("id") if child_asset else None,
                child_asset.get("asset_tag") if child_asset else None,
                child_asset.get("serial") if child_asset else None,
                child_asset.get("name") if child_asset else None,
                1 if ok else 0,
                message,
            ),
        )
        conn.commit()

        return {
            "id": cur.lastrowid,
            "created_at": _format_timestamp(created_at),
            "ok": ok,
            "message": message,
        }


def get_recent(limit: int = 50) -> list[dict]:
    init_db()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM checkout_asset_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        item["created_at"] = _format_timestamp(item.get("created_at"))
        results.append(item)

    return results