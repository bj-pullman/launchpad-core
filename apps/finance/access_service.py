from datetime import datetime, timezone

from modules.core.identity.rbac_service import get_user_permission_keys

from .db import get_connection
from .service import list_enabled_departments


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_finance_permission_keys(user_id: int) -> set[str]:
    return set(get_user_permission_keys(user_id))


# -----------------------------
# Finance Access Levels
# -----------------------------
def has_finance_view(user_id: int) -> bool:
    permissions = get_finance_permission_keys(user_id)
    return any(
        key in permissions
        for key in {
            "finance.home.view",
            "finance.view",
            "finance.records.view",
        }
    )


def has_finance_operator(user_id: int) -> bool:
    permissions = get_finance_permission_keys(user_id)
    return any(
        key in permissions
        for key in {
            "finance.operator",
            "finance.admin",
            "finance.records.operator",
            "finance.records.admin",
        }
    )


def has_finance_admin(user_id: int) -> bool:
    permissions = get_finance_permission_keys(user_id)
    return any(
        key in permissions
        for key in {
            "finance.admin",
            "finance.records.admin",
            "finance.vendors.admin",
            "finance.imports.admin",
        }
    )


# -----------------------------
# Budget Access (SEPARATE)
# -----------------------------
def has_budget_view(user_id: int) -> bool:
    permissions = get_finance_permission_keys(user_id)
    return any(
        key in permissions
        for key in {
            "finance.budget.view",
            "finance.budget.operator",
            "finance.budget.admin",
        }
    )


def has_budget_operator(user_id: int) -> bool:
    permissions = get_finance_permission_keys(user_id)
    return any(
        key in permissions
        for key in {
            "finance.budget.operator",
            "finance.budget.admin",
        }
    )


def has_budget_admin(user_id: int) -> bool:
    permissions = get_finance_permission_keys(user_id)
    return "finance.budget.admin" in permissions


# -----------------------------
# Department Scope
# -----------------------------
def list_department_assignments_for_user(
    user_id: int,
    area_key: str = "finance",
) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_user_department_scope
            WHERE user_id = ?
              AND area_key = ?
            ORDER BY department_name COLLATE NOCASE
            """,
            (user_id, area_key),
        ).fetchall()

    return [dict(row) for row in rows]


def list_accessible_departments_for_user(user_id: int) -> list[dict]:
    if has_finance_admin(user_id):
        return list_enabled_departments()

    assignments = list_department_assignments_for_user(user_id, area_key="finance")
    if not assignments:
        return []

    assigned_names = {
        (row.get("department_name") or "").strip()
        for row in assignments
        if (row.get("department_name") or "").strip()
    }

    departments = list_enabled_departments()
    return [
        item for item in departments
        if (item.get("department_name") or "").strip() in assigned_names
    ]


def can_access_department(user_id: int, department_name: str) -> bool:
    department_name = (department_name or "").strip()
    if not department_name:
        return False

    return any(
        (item.get("department_name") or "").strip() == department_name
        for item in list_accessible_departments_for_user(user_id)
    )


def can_manage_department(user_id: int, department_name: str) -> bool:
    department_name = (department_name or "").strip()
    if not department_name:
        return False

    if has_finance_admin(user_id):
        return True

    assignments = list_department_assignments_for_user(user_id, area_key="finance")
    return any(
        (row.get("department_name") or "").strip() == department_name
        and (row.get("scope_level") or "").strip().lower() in {"operator", "admin"}
        for row in assignments
    )


def can_access_budget_department(user_id: int, department_name: str) -> bool:
    department_name = (department_name or "").strip()
    if not department_name or not has_budget_view(user_id):
        return False

    if has_budget_admin(user_id):
        return True

    assignments = list_department_assignments_for_user(user_id, area_key="budget")
    return any(
        (row.get("department_name") or "").strip() == department_name
        for row in assignments
    )


# -----------------------------
# Scope Management
# -----------------------------
def grant_department_scope(
    user_id: int,
    department_name: str,
    area_key: str = "finance",
    scope_level: str = "operator",
):
    department_name = (department_name or "").strip()
    area_key = (area_key or "finance").strip().lower()
    scope_level = (scope_level or "operator").strip().lower()

    if not department_name:
        raise ValueError("department_name is required")
    if area_key not in {"finance", "budget"}:
        raise ValueError("area_key must be finance or budget")
    if scope_level not in {"view", "operator", "admin"}:
        raise ValueError("scope_level must be view, operator, or admin")

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO finance_user_department_scope (
                user_id,
                department_name,
                area_key,
                scope_level,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, department_name, area_key)
            DO UPDATE SET
                scope_level = excluded.scope_level,
                updated_at = excluded.updated_at
            """,
            (user_id, department_name, area_key, scope_level, now, now),
        )
        conn.commit()


def revoke_department_scope(
    user_id: int,
    department_name: str,
    area_key: str = "finance",
):
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM finance_user_department_scope
            WHERE user_id = ?
              AND department_name = ?
              AND area_key = ?
            """,
            (user_id, department_name.strip(), area_key.strip().lower()),
        )
        conn.commit()