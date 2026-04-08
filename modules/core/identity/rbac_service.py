from datetime import datetime, timezone

from modules.core.identity.rbac_db import get_connection


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


def update_role(role_id: int, role_name: str, description: str | None = None):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE roles
            SET role_name = ?, description = ?, updated_at = ?
            WHERE id = ?
            """,
            (role_name, description, now, role_id),
        )
        conn.commit()


def delete_role(role_id: int):
    with get_connection() as conn:
        role = conn.execute(
            """
            SELECT *
            FROM roles
            WHERE id = ?
            """,
            (role_id,),
        ).fetchone()

        if not role:
            return

        if int(role["is_system"]) == 1:
            raise ValueError("System groups cannot be deleted.")

        conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
        conn.execute("DELETE FROM user_roles WHERE role_id = ?", (role_id,))
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
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
            """
            SELECT *
            FROM roles
            WHERE role_key = ?
            """,
            (role_key,),
        ).fetchone()

    return row_to_dict(row)


def get_role_by_id(role_id: int):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM roles
            WHERE id = ?
            """,
            (role_id,),
        ).fetchone()

    return row_to_dict(row)


def get_permission_by_key(permission_key: str):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM permissions
            WHERE permission_key = ?
            """,
            (permission_key,),
        ).fetchone()

    return row_to_dict(row)


def get_permission_by_id(permission_id: int):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM permissions
            WHERE id = ?
            """,
            (permission_id,),
        ).fetchone()

    return row_to_dict(row)


def list_roles(include_system: bool = True) -> list[dict]:
    sql = """
        SELECT *
        FROM roles
    """
    params = []

    if not include_system:
        sql += " WHERE is_system = 0"

    sql += " ORDER BY is_system DESC, role_name"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]


def list_permissions() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM permissions
            ORDER BY permission_key
            """
        ).fetchall()

    return [dict(row) for row in rows]


def assign_permission_to_role(role_key: str, permission_key: str):
    role = get_role_by_key(role_key)
    permission = get_permission_by_key(permission_key)

    if not role:
        raise ValueError(f"Role not found: {role_key}")

    if not permission:
        raise ValueError(f"Permission not found: {permission_key}")

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


def replace_role_permissions(role_id: int, permission_keys: list[str]):
    now = utc_now_iso()

    with get_connection() as conn:
        role = conn.execute(
            """
            SELECT *
            FROM roles
            WHERE id = ?
            """,
            (role_id,),
        ).fetchone()

        if not role:
            raise ValueError("Group not found.")

        conn.execute(
            """
            DELETE FROM role_permissions
            WHERE role_id = ?
            """,
            (role_id,),
        )

        if permission_keys:
            rows = conn.execute(
                f"""
                SELECT id, permission_key
                FROM permissions
                WHERE permission_key IN ({",".join("?" for _ in permission_keys)})
                """,
                permission_keys,
            ).fetchall()

            permission_map = {row["permission_key"]: row["id"] for row in rows}

            for key in permission_keys:
                permission_id = permission_map.get(key)
                if permission_id:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO role_permissions (
                            role_id,
                            permission_id,
                            created_at
                        )
                        VALUES (?, ?, ?)
                        """,
                        (role_id, permission_id, now),
                    )

        conn.commit()


def get_role_permissions(role_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.*
            FROM role_permissions rp
            INNER JOIN permissions p ON p.id = rp.permission_id
            WHERE rp.role_id = ?
            ORDER BY p.permission_key
            """,
            (role_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_role_permission_keys(role_id: int) -> set[str]:
    return {permission["permission_key"] for permission in get_role_permissions(role_id)}


def assign_role_to_user(user_id: int, role_key: str):
    role = get_role_by_key(role_key)
    if not role:
        raise ValueError(f"Role not found: {role_key}")

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


def replace_user_roles(user_id: int, role_keys: list[str]):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM user_roles
            WHERE user_id = ?
            """,
            (user_id,),
        )

        if role_keys:
            rows = conn.execute(
                f"""
                SELECT id, role_key
                FROM roles
                WHERE role_key IN ({",".join("?" for _ in role_keys)})
                """,
                role_keys,
            ).fetchall()

            role_map = {row["role_key"]: row["id"] for row in rows}

            for key in role_keys:
                role_id = role_map.get(key)
                if role_id:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO user_roles (
                            user_id,
                            role_id,
                            created_at
                        )
                        VALUES (?, ?, ?)
                        """,
                        (user_id, role_id, now),
                    )

        conn.commit()


def remove_role_from_user(user_id: int, role_key: str):
    role = get_role_by_key(role_key)
    if not role:
        return

    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM user_roles
            WHERE user_id = ? AND role_id = ?
            """,
            (user_id, role["id"]),
        )
        conn.commit()


def clear_user_roles(user_id: int):
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM user_roles
            WHERE user_id = ?
            """,
            (user_id,),
        )
        conn.commit()


def get_user_roles(user_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT r.*
            FROM user_roles ur
            INNER JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = ?
            ORDER BY r.role_name
            """,
            (user_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_user_role_keys(user_id: int) -> set[str]:
    return {role["role_key"] for role in get_user_roles(user_id)}


def assign_permission_to_user(user_id: int, permission_key: str):
    permission = get_permission_by_key(permission_key)
    if not permission:
        raise ValueError(f"Permission not found: {permission_key}")

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO user_permissions (
                user_id,
                permission_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (user_id, permission["id"], now),
        )
        conn.commit()


def replace_user_permissions(user_id: int, permission_keys: list[str]):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM user_permissions
            WHERE user_id = ?
            """,
            (user_id,),
        )

        if permission_keys:
            rows = conn.execute(
                f"""
                SELECT id, permission_key
                FROM permissions
                WHERE permission_key IN ({",".join("?" for _ in permission_keys)})
                """,
                permission_keys,
            ).fetchall()

            permission_map = {row["permission_key"]: row["id"] for row in rows}

            for key in permission_keys:
                permission_id = permission_map.get(key)
                if permission_id:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO user_permissions (
                            user_id,
                            permission_id,
                            created_at
                        )
                        VALUES (?, ?, ?)
                        """,
                        (user_id, permission_id, now),
                    )

        conn.commit()


def get_user_direct_permissions(user_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.*
            FROM user_permissions up
            INNER JOIN permissions p ON p.id = up.permission_id
            WHERE up.user_id = ?
            ORDER BY p.permission_key
            """,
            (user_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_user_direct_permission_keys(user_id: int) -> set[str]:
    return {permission["permission_key"] for permission in get_user_direct_permissions(user_id)}


def get_user_group_permissions(user_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT p.*
            FROM user_roles ur
            INNER JOIN role_permissions rp ON rp.role_id = ur.role_id
            INNER JOIN permissions p ON p.id = rp.permission_id
            WHERE ur.user_id = ?
            ORDER BY p.permission_key
            """,
            (user_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_user_group_permission_keys(user_id: int) -> set[str]:
    return {permission["permission_key"] for permission in get_user_group_permissions(user_id)}


def get_user_permissions(user_id: int) -> list[dict]:
    group_permissions = get_user_group_permissions(user_id)
    direct_permissions = get_user_direct_permissions(user_id)

    seen = {}
    for permission in group_permissions + direct_permissions:
        seen[permission["permission_key"]] = permission

    return [seen[key] for key in sorted(seen.keys())]


def get_user_permission_keys(user_id: int) -> set[str]:
    return {permission["permission_key"] for permission in get_user_permissions(user_id)}


def user_has_permission(user_id: int, permission_key: str) -> bool:
    role_keys = get_user_role_keys(user_id)
    if "super_admin" in role_keys:
        return True

    return permission_key in get_user_permission_keys(user_id)


def build_permission_catalog() -> list[dict]:
    catalog = []

    allowed_staff_status_keys = {
        "staff_status.app.view",
        "staff_status.view",
        "staff_status.operator",
        "staff_status.admin",
        "launchpad.settings.staff_status.view",
        "launchpad.settings.staff_status.manage",
    }

    for permission in list_permissions():
        key = permission["permission_key"]

        if key.startswith("staff_status.") and key not in allowed_staff_status_keys:
            continue

        action = "manage" if key.endswith(".manage") else "view"

        if key == "staff_status.app.view":
            section = "Staff Status"
            group = "Staff Status"
            clean_label = "Staff Status App"
            action = "view"
        elif key == "staff_status.view":
            section = "Staff Status"
            group = "Staff Status"
            clean_label = "Staff Status"
            action = "view"
        elif key == "staff_status.operator":
            section = "Staff Status"
            group = "Staff Status"
            clean_label = "Staff Status"
            action = "operator"
        elif key == "staff_status.admin":
            section = "Staff Status"
            group = "Staff Status"
            clean_label = "Staff Status"
            action = "admin"
        else:
            label = permission["permission_name"]
            if label.startswith("Manage "):
                clean_label = label.replace("Manage ", "", 1)
            else:
                clean_label = label.replace(" Settings", "")

            if key.startswith("launchpad.settings.general"):
                section = "Launchpad Settings"
                group = "General"
            elif key.startswith("launchpad.settings.snipeops"):
                section = "Launchpad Settings"
                group = "SnipeOps"
            elif key.startswith("launchpad.settings.saml"):
                section = "Launchpad Settings"
                group = "SAML"
            elif key.startswith("launchpad.settings.security"):
                section = "Launchpad Settings"
                group = "Security"
            elif key.startswith("launchpad.settings.groups"):
                section = "Launchpad Settings"
                group = "Groups"
            elif key.startswith("launchpad.settings.users"):
                section = "Launchpad Settings"
                group = "Users"
            elif key.startswith("launchpad.settings.staff_status"):
                section = "Launchpad Settings"
                group = "Staff Status"
            elif key.startswith("launchpad.settings"):
                section = "Launchpad Settings"
                group = "General"
            elif key.startswith("launchpad.home"):
                section = "Launchpad"
                group = "Dashboard"
                clean_label = "Dashboard"
            elif key.startswith("snipeops."):
                section = "SnipeOps"
                group = "SnipeOps"
            elif key.startswith("finance."):
                section = "Finance"
                group = "Finance"
            elif key.startswith("user360."):
                section = "User360"
                group = "User360"
            elif key.startswith("gam."):
                section = "GAM"
                group = "GAM"
            elif key.startswith("newhire."):
                section = "New Hire Intake"
                group = "New Hire Intake"
            elif key.startswith("virtual_students."):
                section = "Virtual Students"
                group = "Virtual Students"
            elif key.startswith("techhub."):
                section = "Tech Hub"
                group = "Tech Hub"
            else:
                section = "Other"
                group = "Other"

        catalog.append({
            "permission_key": key,
            "permission_name": permission["permission_name"],
            "display_label": clean_label,
            "section": section,
            "group": group,
            "action": action,
        })

    return sorted(
        catalog,
        key=lambda item: (
            item["section"],
            item["group"],
            item["display_label"],
            item["action"],
        ),
    )


def build_user_access_summary(user_id: int) -> dict:
    roles = get_user_roles(user_id)
    role_keys = {role["role_key"] for role in roles}

    direct_permissions = get_user_direct_permissions(user_id)
    group_permissions = get_user_group_permissions(user_id)
    effective_permissions = get_user_permissions(user_id)

    return {
        "is_super_admin": "super_admin" in role_keys,
        "roles": roles,
        "direct_permissions": direct_permissions,
        "group_permissions": group_permissions,
        "effective_permissions": effective_permissions,
    }