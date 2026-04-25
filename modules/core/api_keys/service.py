import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone

from modules.core.settings.settings_db import get_connection


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_api_keys_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS launchpad_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                friendly_name TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                last_used_action TEXT,
                revoked_at TEXT,
                revoked_by_user_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.commit()


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def create_api_key(*, friendly_name: str, created_by_user_id: int | None):
    friendly_name = (friendly_name or "").strip()
    if not friendly_name:
        raise ValueError("Friendly name is required.")

    raw_key = f"lp_live_{secrets.token_urlsafe(64)}"
    key_prefix = raw_key[:16]
    key_hash = _hash_key(raw_key)
    now = utc_now_iso()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO launchpad_api_keys (
                friendly_name,
                key_prefix,
                key_hash,
                created_by_user_id,
                created_at,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                friendly_name,
                key_prefix,
                key_hash,
                created_by_user_id,
                now,
            ),
        )
        conn.commit()

    return {
        "id": cursor.lastrowid,
        "raw_key": raw_key,
        "key_prefix": key_prefix,
        "friendly_name": friendly_name,
        "created_at": now,
    }


def list_api_keys():
    init_api_keys_db()

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                id,
                friendly_name,
                key_prefix,
                scopes_json,
                created_by_user_id,
                created_at,
                last_used_at,
                last_used_action,
                revoked_at,
                revoked_by_user_id,
                is_active
            FROM launchpad_api_keys
            ORDER BY is_active DESC, created_at DESC
        """).fetchall()

    keys = []
    for row in rows:
        item = dict(row)
        try:
            item["scopes"] = json.loads(item.get("scopes_json") or "[]")
        except json.JSONDecodeError:
            item["scopes"] = []
        keys.append(item)

    return keys


def revoke_api_key(*, api_key_id: int, revoked_by_user_id: int | None):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE launchpad_api_keys
            SET is_active = 0,
                revoked_at = ?,
                revoked_by_user_id = ?
            WHERE id = ?
            """,
            (now, revoked_by_user_id, api_key_id),
        )
        conn.commit()


def verify_api_key(provided_key: str | None):
    if not provided_key:
        return None

    provided_hash = _hash_key(provided_key.strip())

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM launchpad_api_keys
            WHERE is_active = 1
        """).fetchall()

    for row in rows:
        item = dict(row)

        if hmac.compare_digest(provided_hash, item["key_hash"]):
            return {
                "id": item["id"],
                "friendly_name": item["friendly_name"],
            }

    return None


def mark_api_key_used(*, api_key_id: int, action: str):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE launchpad_api_keys
            SET last_used_at = ?,
                last_used_action = ?
            WHERE id = ?
            """,
            (utc_now_iso(), action, api_key_id),
        )
        conn.commit()

def delete_api_key(*, api_key_id: int):
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM launchpad_api_keys
            WHERE id = ?
              AND is_active = 0
            """,
            (api_key_id,),
        )
        conn.commit()