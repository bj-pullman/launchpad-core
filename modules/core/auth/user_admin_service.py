from datetime import datetime, timezone

from modules.core.auth.local_auth_db import get_connection
from modules.core.auth.passwords import hash_password
from modules.core.identity.rbac_service import clear_user_roles, assign_role_to_user
from modules.core.utils.time import utc_now_iso

def create_sso_stub_user(user_id: int, username: str, is_active: int = 1):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO local_auth_accounts (
                user_id,
                username,
                password_hash,
                is_active,
                is_breakglass,
                last_login_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, NULL, ?, 0, NULL, ?, ?)
            """,
            (user_id, username.strip().lower(), int(is_active), now, now),
        )
        conn.commit()

def update_last_login_at(user_id: int):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE local_auth_accounts
            SET last_login_at = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (now, now, user_id),
        )
        conn.commit()

def list_local_users():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                la.user_id,
                la.username,
                la.is_active,
                la.is_breakglass,
                la.last_login_at,
                la.created_at,
                la.updated_at
            FROM local_auth_accounts la
            ORDER BY la.username
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_local_user_by_user_id(user_id: int):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                la.user_id,
                la.username,
                la.is_active,
                la.is_breakglass,
                la.last_login_at,
                la.created_at,
                la.updated_at
            FROM local_auth_accounts la
            WHERE la.user_id = ?
            """,
            (user_id,),
        ).fetchone()

    return dict(row) if row else None


def create_local_user(user_id: int, username: str, password: str, is_active: int = 1):
    now = utc_now_iso()
    password_hash = hash_password(password)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO local_auth_accounts (
                user_id,
                username,
                password_hash,
                is_active,
                is_breakglass,
                last_login_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, 0, NULL, ?, ?)
            """,
            (user_id, username.strip().lower(), password_hash, int(is_active), now, now),
        )
        conn.commit()


def update_local_user(user_id: int, username: str, is_active: int):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE local_auth_accounts
            SET username = ?, is_active = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (username.strip().lower(), int(is_active), now, user_id),
        )
        conn.commit()


def set_local_user_password(user_id: int, password: str):
    now = utc_now_iso()
    password_hash = hash_password(password)

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE local_auth_accounts
            SET password_hash = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (password_hash, now, user_id),
        )
        conn.commit()


def replace_user_roles(user_id: int, role_keys: list[str]):
    clear_user_roles(user_id)

    if not role_keys:
        role_keys = ["viewer"]

    for role_key in role_keys:
        assign_role_to_user(user_id, role_key)