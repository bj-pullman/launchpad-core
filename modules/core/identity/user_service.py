from datetime import datetime, timezone

from modules.core.identity.identity_db import get_connection


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    value = email.strip().lower()
    return value or None


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()
    return value or None


def normalize_bool_to_int(value) -> int:
    if isinstance(value, bool):
        return 1 if value else 0

    if value in (1, "1", "true", "True", "yes", "Yes", "on", "ON"):
        return 1

    return 0


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def build_user_payload(data: dict) -> dict:
    return {
        "source_type": normalize_text(data.get("source_type")),
        "source_id": normalize_text(data.get("source_id")),
        "email": normalize_email(data.get("email")),
        "username": normalize_text(data.get("username")),
        "display_name": normalize_text(data.get("display_name")),
        "first_name": normalize_text(data.get("first_name")),
        "last_name": normalize_text(data.get("last_name")),
        "is_active": normalize_bool_to_int(data.get("is_active", 1)),
        "job_title": normalize_text(data.get("job_title")),
        "department": normalize_text(data.get("department")),
        "office_location": normalize_text(data.get("office_location")),
        "company_name": normalize_text(data.get("company_name")),
        "employee_id": normalize_text(data.get("employee_id")),
        "preferred_language": normalize_text(data.get("preferred_language")),
        "business_phone": normalize_text(data.get("business_phone")),
        "mobile_phone": normalize_text(data.get("mobile_phone")),
        "manager_source_id": normalize_text(data.get("manager_source_id")),
        "manager_email": normalize_email(data.get("manager_email")),
        "manager_display_name": normalize_text(data.get("manager_display_name")),
        "last_synced_at": normalize_text(data.get("last_synced_at")),
    }


def get_user_by_email(email: str):
    normalized_email = normalize_email(email)
    if not normalized_email:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (normalized_email,),
        ).fetchone()

    return row_to_dict(row)


def get_user_by_id(user_id: int):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    return row_to_dict(row)


def create_user(data: dict):
    payload = build_user_payload(data)

    if not payload["email"]:
        raise ValueError("email is required")

    if not payload["display_name"]:
        raise ValueError("display_name is required")

    now = utc_now_iso()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (
                source_type,
                source_id,
                email,
                username,
                display_name,
                first_name,
                last_name,
                is_active,
                job_title,
                department,
                office_location,
                company_name,
                employee_id,
                preferred_language,
                business_phone,
                mobile_phone,
                manager_source_id,
                manager_email,
                manager_display_name,
                last_synced_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["source_type"],
                payload["source_id"],
                payload["email"],
                payload["username"],
                payload["display_name"],
                payload["first_name"],
                payload["last_name"],
                payload["is_active"],
                payload["job_title"],
                payload["department"],
                payload["office_location"],
                payload["company_name"],
                payload["employee_id"],
                payload["preferred_language"],
                payload["business_phone"],
                payload["mobile_phone"],
                payload["manager_source_id"],
                payload["manager_email"],
                payload["manager_display_name"],
                payload["last_synced_at"],
                now,
                now,
            ),
        )
        conn.commit()
        user_id = cursor.lastrowid

    return get_user_by_id(user_id)


def update_user(user_id: int, data: dict):
    payload = build_user_payload(data)
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET
                source_type = ?,
                source_id = ?,
                email = ?,
                username = ?,
                display_name = ?,
                first_name = ?,
                last_name = ?,
                is_active = ?,
                job_title = ?,
                department = ?,
                office_location = ?,
                company_name = ?,
                employee_id = ?,
                preferred_language = ?,
                business_phone = ?,
                mobile_phone = ?,
                manager_source_id = ?,
                manager_email = ?,
                manager_display_name = ?,
                last_synced_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                payload["source_type"],
                payload["source_id"],
                payload["email"],
                payload["username"],
                payload["display_name"],
                payload["first_name"],
                payload["last_name"],
                payload["is_active"],
                payload["job_title"],
                payload["department"],
                payload["office_location"],
                payload["company_name"],
                payload["employee_id"],
                payload["preferred_language"],
                payload["business_phone"],
                payload["mobile_phone"],
                payload["manager_source_id"],
                payload["manager_email"],
                payload["manager_display_name"],
                payload["last_synced_at"],
                now,
                user_id,
            ),
        )
        conn.commit()

    return get_user_by_id(user_id)


def upsert_user(data: dict):
    payload = build_user_payload(data)

    if not payload["email"]:
        raise ValueError("email is required")

    if not payload["display_name"]:
        raise ValueError("display_name is required")

    existing_user = get_user_by_email(payload["email"])

    if existing_user:
        return update_user(existing_user["id"], payload)

    return create_user(payload)