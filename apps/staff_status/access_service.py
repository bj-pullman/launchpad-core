from .db import get_connection
from datetime import datetime, timezone
from modules.core.identity.rbac_service import (
    get_user_direct_permission_keys,
    get_user_roles,
    get_user_permission_keys
)
from .service import list_enabled_departments
from modules.core.identity.identity_db import get_connection as get_identity_connection

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_staff_status_permission_keys(user_id: int) -> set[str]:
    return set(get_user_permission_keys(user_id))


def has_staff_status_view(user_id: int) -> bool:
    permissions = get_staff_status_permission_keys(user_id)
    return any(
        key in permissions
        for key in {
            "staff_status.view",
            "staff_status.operator",
            "staff_status.admin",
        }
    )


def has_staff_status_operator(user_id: int) -> bool:
    permissions = get_staff_status_permission_keys(user_id)
    return any(
        key in permissions
        for key in {
            "staff_status.operator",
            "staff_status.admin",
        }
    )


def has_staff_status_admin(user_id: int) -> bool:
    permissions = get_staff_status_permission_keys(user_id)
    return "staff_status.admin" in permissions


def list_department_assignments_for_user(user_id: int) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT department_name
            FROM staff_status_department_access
            WHERE user_id = ?
            ORDER BY department_name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()

    return [row["department_name"] for row in rows]


def list_globally_accessible_departments_for_user(user_id: int) -> list[dict]:
    if not has_staff_status_view(user_id):
        return []
    return list_enabled_departments()


def list_scoped_departments_for_user(user_id: int) -> list[dict]:
    assigned = {name.strip() for name in list_department_assignments_for_user(user_id) if name.strip()}
    if not assigned:
        return []

    departments = list_enabled_departments()
    return [
        item for item in departments
        if (item.get("department_name") or "").strip() in assigned
    ]


def list_accessible_departments_for_user(user_id: int) -> list[dict]:
    if has_staff_status_view(user_id):
        return list_globally_accessible_departments_for_user(user_id)

    return list_scoped_departments_for_user(user_id)


def can_access_department(user_id: int, department_name: str) -> bool:
    department_name = (department_name or "").strip()
    if not department_name:
        return False

    departments = list_accessible_departments_for_user(user_id)
    return any(
        (item.get("department_name") or "").strip() == department_name
        for item in departments
    )


def can_operate_department(user_id: int, department_name: str) -> bool:
    department_name = (department_name or "").strip()
    if not department_name:
        return False

    if has_staff_status_operator(user_id):
        return True

    assigned = {name.strip() for name in list_department_assignments_for_user(user_id) if name.strip()}
    return department_name in assigned

def list_department_access_rows() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM staff_status_department_access
            ORDER BY department_name COLLATE NOCASE, user_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def grant_department_access(user_id: int, department_name: str):
    department_name = (department_name or "").strip()
    if not department_name:
        raise ValueError("department_name is required")

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO staff_status_department_access (
                user_id,
                department_name,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, department_name)
            DO UPDATE SET updated_at = excluded.updated_at
            """,
            (user_id, department_name, now, now),
        )
        conn.commit()


def revoke_department_access(user_id: int, department_name: str):
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM staff_status_department_access
            WHERE user_id = ? AND department_name = ?
            """,
            (user_id, department_name.strip()),
        )
        conn.commit()
        
def list_department_access_with_users() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.user_id,
                a.department_name,
                a.created_at,
                a.updated_at
            FROM staff_status_department_access a
            ORDER BY a.department_name COLLATE NOCASE, a.user_id
            """
        ).fetchall()

    assignments = [dict(row) for row in rows]
    if not assignments:
        return []

    user_ids = sorted({row["user_id"] for row in assignments if row.get("user_id")})
    placeholders = ",".join("?" for _ in user_ids)

    with get_identity_connection() as conn:
        user_rows = conn.execute(
            f"""
            SELECT id, email, display_name, first_name, last_name, is_active
            FROM users
            WHERE id IN ({placeholders})
            """,
            user_ids,
        ).fetchall()

    user_map = {row["id"]: dict(row) for row in user_rows}

    enriched = []
    for row in assignments:
        user = user_map.get(row["user_id"], {})
        display_name = (
            (user.get("display_name") or "").strip()
            or f"{(user.get('first_name') or '').strip()} {(user.get('last_name') or '').strip()}".strip()
            or (user.get("email") or "").strip()
        )

        enriched.append(
            {
                **row,
                "email": user.get("email", ""),
                "display_name": display_name,
                "is_active": user.get("is_active", 0),
            }
        )

    return enriched

def _resolve_display_name(user: dict) -> str:
    display_name = (user.get("display_name") or "").strip()
    if display_name:
        return display_name

    first_name = (user.get("first_name") or "").strip()
    last_name = (user.get("last_name") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name

    return (user.get("email") or "").strip() or f"User {user.get('id')}"


def list_staff_status_access_with_users() -> list[dict]:
    with get_identity_connection() as conn:
        user_rows = conn.execute(
            """
            SELECT *
            FROM users
            WHERE is_active = 1
            ORDER BY COALESCE(NULLIF(TRIM(display_name), ''), email) COLLATE NOCASE
            """
        ).fetchall()

    users = [dict(row) for row in user_rows]
    output = []
    global_user_ids = set()

    for user in users:
        user_id = user["id"]
        role_keys = {role["role_key"] for role in get_user_roles(user_id)}
        effective_permissions = set(get_user_permission_keys(user_id))

        display_name = _resolve_display_name(user)
        email = user.get("email", "")

        if "super_admin" in role_keys:
            output.append(
                {
                    "user_id": user_id,
                    "display_name": display_name,
                    "email": email,
                    "access_level": "Admin",
                    "scope_label": "All Departments",
                    "department_name": None,
                    "access_source": "Role",
                    "can_remove": False,
                }
            )
            global_user_ids.add(user_id)
            continue

        if "staff_status.admin" in effective_permissions:
            output.append(
                {
                    "user_id": user_id,
                    "display_name": display_name,
                    "email": email,
                    "access_level": "Admin",
                    "scope_label": "All Departments",
                    "department_name": None,
                    "access_source": "Global Permission",
                    "can_remove": False,
                }
            )
            global_user_ids.add(user_id)
            continue

        if "staff_status.operator" in effective_permissions:
            output.append(
                {
                    "user_id": user_id,
                    "display_name": display_name,
                    "email": email,
                    "access_level": "Operator",
                    "scope_label": "All Departments",
                    "department_name": None,
                    "access_source": "Global Permission",
                    "can_remove": False,
                }
            )
            global_user_ids.add(user_id)
            continue

        if "staff_status.view" in effective_permissions:
            output.append(
                {
                    "user_id": user_id,
                    "display_name": display_name,
                    "email": email,
                    "access_level": "View",
                    "scope_label": "All Departments",
                    "department_name": None,
                    "access_source": "Global Permission",
                    "can_remove": False,
                }
            )
            global_user_ids.add(user_id)
            continue

    with get_connection() as conn:
        scoped_rows = conn.execute(
            """
            SELECT user_id, department_name, created_at, updated_at
            FROM staff_status_department_access
            ORDER BY department_name COLLATE NOCASE, user_id
            """
        ).fetchall()

    user_map = {user["id"]: user for user in users}

    for row in scoped_rows:
        row = dict(row)
        user_id = row["user_id"]

        if user_id in global_user_ids:
            continue

        user = user_map.get(user_id)
        if not user:
            continue

        output.append(
            {
                "user_id": user_id,
                "display_name": _resolve_display_name(user),
                "email": user.get("email", ""),
                "access_level": "Operator",
                "scope_label": row["department_name"],
                "department_name": row["department_name"],
                "access_source": "Assigned",
                "can_remove": True,
            }
        )

    return output