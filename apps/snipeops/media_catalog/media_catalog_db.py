from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from config.settings import SNIPE_CATALOG_DB_PATH


DB_PATH = Path(SNIPE_CATALOG_DB_PATH).with_name("snipeops_media_catalog.sqlite3")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS media_catalog_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            action TEXT NOT NULL,
            cart_asset_id INTEGER,
            cart_asset_tag TEXT,
            cart_asset_name TEXT,
            device_asset_id INTEGER,
            device_asset_tag TEXT,
            device_serial TEXT,
            device_name TEXT,
            ok INTEGER NOT NULL DEFAULT 0,
            message TEXT
        )
        """)

        with _connect() as conn:
            existing_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(media_catalog_logs)").fetchall()
            }

            if "actor_user_id" not in existing_columns:
                conn.execute("ALTER TABLE media_catalog_logs ADD COLUMN actor_user_id INTEGER")

            if "actor_email" not in existing_columns:
                conn.execute("ALTER TABLE media_catalog_logs ADD COLUMN actor_email TEXT")

            if "actor_display_name" not in existing_columns:
                conn.execute("ALTER TABLE media_catalog_logs ADD COLUMN actor_display_name TEXT")

            conn.commit()

        conn.execute("""
        CREATE TABLE IF NOT EXISTS media_cart_ownership (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cart_asset_id INTEGER NOT NULL UNIQUE,
            cart_asset_tag TEXT,
            cart_name TEXT,
            owner_user_id INTEGER,
            owner_email TEXT,
            owner_display_name TEXT,
            claimed_at TEXT,
            updated_at TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS media_cart_ownership_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            cart_asset_id INTEGER NOT NULL,
            cart_asset_tag TEXT,
            cart_name TEXT,
            action TEXT NOT NULL,
            previous_owner_user_id INTEGER,
            previous_owner_email TEXT,
            previous_owner_display_name TEXT,
            new_owner_user_id INTEGER,
            new_owner_email TEXT,
            new_owner_display_name TEXT
        )
        """)

        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(media_cart_ownership)").fetchall()
        }

        if "media_specialist_owner" not in existing_columns:
            conn.execute("ALTER TABLE media_cart_ownership ADD COLUMN media_specialist_owner TEXT")

        if "teacher_name" not in existing_columns:
            conn.execute("ALTER TABLE media_cart_ownership ADD COLUMN teacher_name TEXT")

        if "room_number" not in existing_columns:
            conn.execute("ALTER TABLE media_cart_ownership ADD COLUMN room_number TEXT")

        if "display_order" not in existing_columns:
            conn.execute("ALTER TABLE media_cart_ownership ADD COLUMN display_order INTEGER")

        conn.commit()


def log_media_action(
    *,
    action: str,
    cart_asset: dict | None,
    device_asset: dict | None,
    ok: bool,
    message: str,
    actor_user: dict | None = None,
) -> dict:
    init_db()
    created_at = _now_iso()

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO media_catalog_logs (
                created_at,
                action,
                cart_asset_id,
                cart_asset_tag,
                cart_asset_name,
                device_asset_id,
                device_asset_tag,
                device_serial,
                device_name,
                ok,
                message,
                actor_user_id,
                actor_email,
                actor_display_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                action,
                cart_asset.get("id") if cart_asset else None,
                cart_asset.get("asset_tag") if cart_asset else None,
                cart_asset.get("name") if cart_asset else None,
                device_asset.get("id") if device_asset else None,
                device_asset.get("asset_tag") if device_asset else None,
                device_asset.get("serial") if device_asset else None,
                device_asset.get("name") if device_asset else None,
                1 if ok else 0,
                message,
                actor_user.get("id") if actor_user else None,
                actor_user.get("email") if actor_user else None,
                actor_user.get("display_name") if actor_user else None,
            ),
        )
        conn.commit()
        return {"id": cur.lastrowid, "created_at": created_at}


def get_recent(limit: int = 50) -> list[dict]:
    init_db()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM media_catalog_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    return [dict(row) for row in rows]


def get_cart_ownership(cart_asset_id: int) -> dict | None:
    init_db()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM media_cart_ownership
            WHERE cart_asset_id = ?
            """,
            (int(cart_asset_id),),
        ).fetchone()

    return dict(row) if row else None


def list_owned_carts(owner_user_id: int) -> list[dict]:
    init_db()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM media_cart_ownership
            WHERE owner_user_id = ?
            ORDER BY
                COALESCE(display_order, 999999),
                cart_asset_tag,
                cart_name
            """,
            (int(owner_user_id),),
        ).fetchall()

    return [dict(row) for row in rows]


def claim_cart(*, cart_asset: dict, user: dict) -> dict:
    init_db()

    now = _now_iso()
    cart_asset_id = int(cart_asset["id"])

    existing = get_cart_ownership(cart_asset_id)

    previous_owner_user_id = existing.get("owner_user_id") if existing else None
    previous_owner_email = existing.get("owner_email") if existing else None
    previous_owner_display_name = existing.get("owner_display_name") if existing else None

    owner_user_id = int(user["id"])
    owner_email = user.get("email") or ""
    owner_display_name = user.get("display_name") or owner_email

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO media_cart_ownership (
                cart_asset_id,
                cart_asset_tag,
                cart_name,
                owner_user_id,
                owner_email,
                owner_display_name,
                claimed_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cart_asset_id) DO UPDATE SET
                cart_asset_tag = excluded.cart_asset_tag,
                cart_name = excluded.cart_name,
                owner_user_id = excluded.owner_user_id,
                owner_email = excluded.owner_email,
                owner_display_name = excluded.owner_display_name,
                updated_at = excluded.updated_at
            """,
            (
                cart_asset_id,
                cart_asset.get("asset_tag"),
                cart_asset.get("name"),
                owner_user_id,
                owner_email,
                owner_display_name,
                now,
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO media_cart_ownership_history (
                created_at,
                cart_asset_id,
                cart_asset_tag,
                cart_name,
                action,
                previous_owner_user_id,
                previous_owner_email,
                previous_owner_display_name,
                new_owner_user_id,
                new_owner_email,
                new_owner_display_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                cart_asset_id,
                cart_asset.get("asset_tag"),
                cart_asset.get("name"),
                "claimed",
                previous_owner_user_id,
                previous_owner_email,
                previous_owner_display_name,
                owner_user_id,
                owner_email,
                owner_display_name,
            ),
        )

        conn.commit()

    return get_cart_ownership(cart_asset_id)

def normalize_cart_order(owner_user_id: int) -> None:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM media_cart_ownership
            WHERE owner_user_id = ?
            ORDER BY
                COALESCE(display_order, 999999),
                cart_asset_tag,
                cart_name
            """,
            (int(owner_user_id),),
        ).fetchall()

        for index, row in enumerate(rows, start=1):
            conn.execute(
                """
                UPDATE media_cart_ownership
                SET display_order = ?, updated_at = ?
                WHERE id = ?
                """,
                (index, _now_iso(), row["id"]),
            )

        conn.commit()


def update_cart_metadata(
    *,
    cart_asset_id: int,
    owner_user_id: int,
    media_specialist_owner: str | None,
    teacher_name: str | None,
    room_number: str | None,
) -> dict:
    init_db()

    with _connect() as conn:
        conn.execute(
            """
            UPDATE media_cart_ownership
            SET
                media_specialist_owner = ?,
                teacher_name = ?,
                room_number = ?,
                updated_at = ?
            WHERE cart_asset_id = ?
              AND owner_user_id = ?
            """,
            (
                (media_specialist_owner or "").strip(),
                (teacher_name or "").strip(),
                (room_number or "").strip(),
                _now_iso(),
                int(cart_asset_id),
                int(owner_user_id),
            ),
        )
        conn.commit()

    return get_cart_ownership(cart_asset_id)


def reorder_owned_cart(
    *,
    owner_user_id: int,
    cart_asset_id: int,
    new_index: int,
) -> list[dict]:
    init_db()
    normalize_cart_order(owner_user_id)

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM media_cart_ownership
            WHERE owner_user_id = ?
            ORDER BY display_order, cart_asset_tag, cart_name
            """,
            (int(owner_user_id),),
        ).fetchall()

        ordered = [dict(row) for row in rows]
        moving = next(
            (row for row in ordered if int(row["cart_asset_id"]) == int(cart_asset_id)),
            None,
        )

        if not moving:
            raise ValueError("Cart is not assigned to this user.")

        ordered = [
            row for row in ordered
            if int(row["cart_asset_id"]) != int(cart_asset_id)
        ]

        target_index = max(1, min(int(new_index), len(ordered) + 1))
        ordered.insert(target_index - 1, moving)

        now = _now_iso()

        for index, row in enumerate(ordered, start=1):
            conn.execute(
                """
                UPDATE media_cart_ownership
                SET display_order = ?, updated_at = ?
                WHERE id = ?
                """,
                (index, now, row["id"]),
            )

        conn.commit()

    return list_owned_carts(owner_user_id)