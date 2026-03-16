from modules.core.identity.identity_db import get_connection
from modules.core.utils.time import utc_now_iso


def create_identity_user(
    email: str,
    display_name: str,
    is_active: int = 1,
    username: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    job_title: str | None = None,
    department: str | None = None,
    office_location: str | None = None,
    company_name: str | None = None,
    employee_id: str | None = None,
    preferred_language: str | None = None,
    business_phone: str | None = None,
    mobile_phone: str | None = None,
    manager_email: str | None = None,
    manager_display_name: str | None = None,
) -> int:
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
                manager_email,
                manager_display_name,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_type,
                source_id,
                email.strip().lower(),
                username.strip().lower() if username else None,
                display_name.strip(),
                first_name.strip() if first_name else None,
                last_name.strip() if last_name else None,
                int(is_active),
                job_title.strip() if job_title else None,
                department.strip() if department else None,
                office_location.strip() if office_location else None,
                company_name.strip() if company_name else None,
                employee_id.strip() if employee_id else None,
                preferred_language.strip() if preferred_language else None,
                business_phone.strip() if business_phone else None,
                mobile_phone.strip() if mobile_phone else None,
                manager_email.strip().lower() if manager_email else None,
                manager_display_name.strip() if manager_display_name else None,
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid