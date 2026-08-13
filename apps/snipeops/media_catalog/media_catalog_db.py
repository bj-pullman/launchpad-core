from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from config.settings import SNIPE_CATALOG_DB_PATH


DB_PATH = Path(SNIPE_CATALOG_DB_PATH).with_name("snipeops_media_catalog.sqlite3")


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return result


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


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

        existing_columns = _table_columns(conn, "media_catalog_logs")

        if "actor_user_id" not in existing_columns:
            conn.execute("ALTER TABLE media_catalog_logs ADD COLUMN actor_user_id INTEGER")

        if "actor_email" not in existing_columns:
            conn.execute("ALTER TABLE media_catalog_logs ADD COLUMN actor_email TEXT")

        if "actor_display_name" not in existing_columns:
            conn.execute("ALTER TABLE media_catalog_logs ADD COLUMN actor_display_name TEXT")

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

        existing_columns = _table_columns(conn, "media_cart_ownership")

        if "media_specialist_owner" not in existing_columns:
            conn.execute("ALTER TABLE media_cart_ownership ADD COLUMN media_specialist_owner TEXT")

        if "teacher_name" not in existing_columns:
            conn.execute("ALTER TABLE media_cart_ownership ADD COLUMN teacher_name TEXT")

        if "room_number" not in existing_columns:
            conn.execute("ALTER TABLE media_cart_ownership ADD COLUMN room_number TEXT")

        if "display_order" not in existing_columns:
            conn.execute("ALTER TABLE media_cart_ownership ADD COLUMN display_order INTEGER")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS media_student_checkouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_asset_id INTEGER NOT NULL,
            device_asset_tag TEXT,
            device_serial TEXT,
            device_name TEXT,
            device_model_name TEXT,
            device_status_name TEXT,
            original_cart_asset_id INTEGER,
            original_cart_asset_tag TEXT,
            original_cart_name TEXT,
            original_cart_teacher_name TEXT,
            original_cart_room_number TEXT,
            original_owner_user_id INTEGER,
            original_owner_email TEXT,
            original_owner_display_name TEXT,
            student_name TEXT NOT NULL,
            student_id TEXT,
            checked_out_at TEXT NOT NULL,
            return_by_date TEXT NOT NULL,
            returned_at TEXT,
            checkout_actor_user_id INTEGER,
            checkout_actor_email TEXT,
            checkout_actor_display_name TEXT,
            return_actor_user_id INTEGER,
            return_actor_email TEXT,
            return_actor_display_name TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            due_date_overridden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_media_student_checkouts_one_active_device
        ON media_student_checkouts(device_asset_id)
        WHERE returned_at IS NULL
        """)

        conn.execute("""
        CREATE INDEX IF NOT EXISTS
            idx_media_student_checkouts_cart
        ON media_student_checkouts(original_cart_asset_id)
        """)

        conn.execute("""
        CREATE INDEX IF NOT EXISTS
            idx_media_student_checkouts_status
        ON media_student_checkouts(status, returned_at)
        """)

        conn.execute("""
        CREATE INDEX IF NOT EXISTS
            idx_media_student_checkouts_return_by
        ON media_student_checkouts(return_by_date)
        """)

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


def create_student_checkout_record(payload: dict) -> dict:
    init_db()

    now = _now_iso()

    values = {
        "device_asset_id": int(payload["device_asset_id"]),
        "device_asset_tag": payload.get("device_asset_tag") or "",
        "device_serial": payload.get("device_serial") or "",
        "device_name": payload.get("device_name") or "",
        "device_model_name": payload.get("device_model_name") or "",
        "device_status_name": payload.get("device_status_name") or "",
        "original_cart_asset_id": payload.get("original_cart_asset_id"),
        "original_cart_asset_tag": payload.get("original_cart_asset_tag") or "",
        "original_cart_name": payload.get("original_cart_name") or "",
        "original_cart_teacher_name": payload.get("original_cart_teacher_name") or "",
        "original_cart_room_number": payload.get("original_cart_room_number") or "",
        "original_owner_user_id": payload.get("original_owner_user_id"),
        "original_owner_email": payload.get("original_owner_email") or "",
        "original_owner_display_name": payload.get("original_owner_display_name") or "",
        "student_name": payload.get("student_name") or "",
        "student_id": payload.get("student_id") or "",
        "checked_out_at": payload["checked_out_at"],
        "return_by_date": payload["return_by_date"],
        "checkout_actor_user_id": payload.get("checkout_actor_user_id"),
        "checkout_actor_email": payload.get("checkout_actor_email") or "",
        "checkout_actor_display_name": payload.get("checkout_actor_display_name") or "",
        "status": payload.get("status") or "active",
        "due_date_overridden": 1 if payload.get("due_date_overridden") else 0,
        "created_at": now,
        "updated_at": now,
    }

    fields = list(values.keys())
    placeholders = ", ".join("?" for _ in fields)

    with _connect() as conn:
        cur = conn.execute(
            f"""
            INSERT INTO media_student_checkouts (
                {", ".join(fields)}
            )
            VALUES ({placeholders})
            """,
            [values[field] for field in fields],
        )
        conn.commit()

        return get_student_checkout(int(cur.lastrowid)) or {}


def get_student_checkout(checkout_id: int) -> dict | None:
    init_db()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM media_student_checkouts
            WHERE id = ?
            """,
            (int(checkout_id),),
        ).fetchone()

    return dict(row) if row else None


def get_active_student_checkout_for_device(device_asset_id: int) -> dict | None:
    init_db()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM media_student_checkouts
            WHERE device_asset_id = ?
              AND returned_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(device_asset_id),),
        ).fetchone()

    return dict(row) if row else None


def list_student_checkouts(
    *,
    cart_asset_ids: list[int] | None = None,
    limit: int = 1000,
) -> list[dict]:
    init_db()

    params: list[object] = []
    where = ""

    if cart_asset_ids is not None:
        normalized_ids = sorted({
            int(cart_asset_id)
            for cart_asset_id in cart_asset_ids
            if cart_asset_id is not None
        })

        if not normalized_ids:
            return []

        placeholders = ", ".join("?" for _ in normalized_ids)
        where = f"WHERE original_cart_asset_id IN ({placeholders})"
        params.extend(normalized_ids)

    params.append(int(limit))

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM media_student_checkouts
            {where}
            ORDER BY
                CASE WHEN returned_at IS NULL THEN 0 ELSE 1 END,
                checked_out_at DESC,
                id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [dict(row) for row in rows]


def list_active_student_checkouts_by_cart_ids(cart_asset_ids: list[int]) -> list[dict]:
    init_db()

    normalized_ids = sorted({
        int(cart_asset_id)
        for cart_asset_id in cart_asset_ids
        if cart_asset_id is not None
    })

    if not normalized_ids:
        return []

    placeholders = ", ".join("?" for _ in normalized_ids)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM media_student_checkouts
            WHERE returned_at IS NULL
              AND original_cart_asset_id IN ({placeholders})
            ORDER BY return_by_date, checked_out_at DESC, id DESC
            """,
            normalized_ids,
        ).fetchall()

    return [dict(row) for row in rows]


def return_student_checkout_record(
    *,
    checkout_id: int,
    actor_user: dict,
    returned_at: str | None = None,
) -> dict | None:
    init_db()

    returned_at = returned_at or _now_iso()
    actor_user = actor_user or {}

    with _connect() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM media_student_checkouts
            WHERE id = ?
            """,
            (int(checkout_id),),
        ).fetchone()

        if not existing:
            return None

        if existing["returned_at"]:
            return dict(existing)

        conn.execute(
            """
            UPDATE media_student_checkouts
            SET
                returned_at = ?,
                return_actor_user_id = ?,
                return_actor_email = ?,
                return_actor_display_name = ?,
                status = 'returned',
                updated_at = ?
            WHERE id = ?
              AND returned_at IS NULL
            """,
            (
                returned_at,
                actor_user.get("id"),
                actor_user.get("email") or "",
                actor_user.get("display_name") or "",
                returned_at,
                int(checkout_id),
            ),
        )
        conn.commit()

    return get_student_checkout(checkout_id)


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

def list_all_owned_carts() -> list[dict]:
    init_db()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM media_cart_ownership
            WHERE owner_user_id IS NOT NULL
            ORDER BY
                owner_display_name,
                owner_email,
                COALESCE(display_order, 999999),
                cart_asset_tag,
                cart_name
            """
        ).fetchall()

    return [dict(row) for row in rows]


def list_cart_owners() -> list[dict]:
    init_db()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                owner_user_id,
                owner_email,
                owner_display_name,
                COUNT(*) AS cart_count,
                MAX(updated_at) AS last_updated_at
            FROM media_cart_ownership
            WHERE owner_user_id IS NOT NULL
            GROUP BY owner_user_id, owner_email, owner_display_name
            ORDER BY owner_display_name, owner_email
            """
        ).fetchall()

    return [dict(row) for row in rows]


def update_cart_metadata_admin(
    *,
    cart_asset_id: int,
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
            """,
            (
                (media_specialist_owner or "").strip(),
                (teacher_name or "").strip(),
                (room_number or "").strip(),
                _now_iso(),
                int(cart_asset_id),
            ),
        )
        conn.commit()

    return get_cart_ownership(cart_asset_id)


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

def unassign_cart(
    *,
    cart_asset_id: int,
    expected_owner_user_id: int | None = None,
) -> dict | None:
    init_db()

    cart_asset_id = int(cart_asset_id)
    now = _now_iso()

    with _connect() as conn:
        ownership_row = conn.execute(
            """
            SELECT *
            FROM media_cart_ownership
            WHERE cart_asset_id = ?
            """,
            (cart_asset_id,),
        ).fetchone()

        if not ownership_row:
            return None

        ownership = dict(ownership_row)
        previous_owner_user_id = ownership.get("owner_user_id")

        if expected_owner_user_id is not None:
            if int(previous_owner_user_id or 0) != int(expected_owner_user_id):
                raise ValueError(
                    "You can only unassign carts that are assigned to you."
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
                ownership.get("cart_asset_tag"),
                ownership.get("cart_name"),
                "unassigned",
                ownership.get("owner_user_id"),
                ownership.get("owner_email"),
                ownership.get("owner_display_name"),
                None,
                None,
                None,
            ),
        )

        conn.execute(
            """
            DELETE FROM media_cart_ownership
            WHERE cart_asset_id = ?
            """,
            (cart_asset_id,),
        )

        if previous_owner_user_id is not None:
            remaining_rows = conn.execute(
                """
                SELECT id
                FROM media_cart_ownership
                WHERE owner_user_id = ?
                ORDER BY
                    COALESCE(display_order, 999999),
                    cart_asset_tag,
                    cart_name
                """,
                (int(previous_owner_user_id),),
            ).fetchall()

            for display_order, row in enumerate(remaining_rows, start=1):
                conn.execute(
                    """
                    UPDATE media_cart_ownership
                    SET display_order = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        display_order,
                        now,
                        row["id"],
                    ),
                )

        conn.commit()

    return ownership

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
