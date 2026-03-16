from datetime import datetime, timezone

from modules.core.auth.local_auth_db import get_connection


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def create_role(role_key: str, role_name: str, description: str | None = None, is_system: int = 0):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO roles (
                role_key,
                role_name,
                description,
                is_system,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (role_key, role_name, description, int(is_system), now, now),
        )
        conn.commit()


def create_permission(permission_key: str, permission_name: str, description: str | None = None):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO permissions (
                permission_key,
                permission_name,
                description,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (permission_key, permission_name, description, now, now),
        )
        conn.commit()


def get_role_by_key(role_key: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM roles WHERE role_key = ?",
            (role_key,),
        ).fetchone()
    return row_to_dict(row)


def get_permission_by_key(permission_key: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM permissions WHERE permission_key = ?",
            (permission_key,),
        ).fetchone()
    return row_to_dict(row)


def assign_permission_to_role(role_key: str, permission_key: str):
    role = get_role_by_key(role_key)
    permission = get_permission_by_key(permission_key)

    if not role or not permission:
        raise ValueError("role or permission not found")

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO role_permissions (
                role_id,
                permission_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (role["id"], permission["id"], now),
        )
        conn.commit()


def assign_role_to_user(user_id: int, role_key: str):
    role = get_role_by_key(role_key)
    if not role:
        raise ValueError("role not found")

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO user_roles (
                user_id,
                role_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (user_id, role["id"], now),
        )
        conn.commit()


def get_user_permission_keys(user_id: int) -> set[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT p.permission_key
            FROM user_roles ur
            INNER JOIN role_permissions rp ON rp.role_id = ur.role_id
            INNER JOIN permissions p ON p.id = rp.permission_id
            WHERE ur.user_id = ?
            """,
            (user_id,),
        ).fetchall()

    return {row["permission_key"] for row in rows}


def user_has_permission(user_id: int, permission_key: str) -> bool:
    return permission_key in get_user_permission_keys(user_id)