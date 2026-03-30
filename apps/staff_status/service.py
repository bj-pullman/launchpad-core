import json
import secrets
from datetime import date, datetime, timezone

from .db import get_connection
from modules.core.identity.identity_db import get_connection as get_identity_connection
from modules.core.settings.settings_service import get_setting


DEFAULT_PUBLIC_ABSENCE_LABEL = "Out of Office"
DEFAULT_LOCATIONS = [
    "EEE",
    "EEM",
    "EEI",
    "Technology Office",
    "SHS",
    "SMS",
    "SIS",
    "SES",
    "Central Office",
    "Annex",
    "Jacket Health",
    "ALA",
    "Off Campus",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_department(value: str | None) -> str | None:
    return normalize_text(value)


def build_display_name(user: dict) -> str:
    display_name = normalize_text(user.get("display_name"))
    if display_name:
        return display_name

    first_name = normalize_text(user.get("first_name")) or ""
    last_name = normalize_text(user.get("last_name")) or ""
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name

    return normalize_text(user.get("email")) or f"User {user['id']}"


def list_active_departments_from_users() -> list[str]:
    with get_identity_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT TRIM(department) AS department_name
            FROM users
            WHERE is_active = 1
              AND department IS NOT NULL
              AND TRIM(department) <> ''
            ORDER BY department_name COLLATE NOCASE
            """
        ).fetchall()

    return [row["department_name"] for row in rows if row["department_name"]]


def list_active_users_for_department(department_name: str) -> list[dict]:
    with get_identity_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM users
            WHERE is_active = 1
              AND TRIM(COALESCE(department, '')) = ?
            ORDER BY COALESCE(NULLIF(TRIM(display_name), ''), TRIM(first_name || ' ' || last_name), email) COLLATE NOCASE
            """,
            (department_name.strip(),),
        ).fetchall()

    users = [dict(row) for row in rows]
    for user in users:
        user["resolved_display_name"] = build_display_name(user)
    return users


def ensure_department_record(department_name: str, home_location_label: str | None = None) -> dict:
    department_name = normalize_department(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    now = utc_now_iso()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM staff_status_departments WHERE department_name = ?",
            (department_name,),
        ).fetchone()

        if existing:
            return dict(existing)

        conn.execute(
            """
            INSERT INTO staff_status_departments (
                department_name,
                is_enabled,
                home_location_label,
                kiosk_enabled,
                kiosk_token,
                kiosk_token_created_at,
                kiosk_token_rotated_at,
                board_enabled,
                created_at,
                updated_at
            )
            VALUES (?, 1, ?, 0, NULL, NULL, NULL, 1, ?, ?)
            """,
            (department_name, normalize_text(home_location_label), now, now),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM staff_status_departments WHERE department_name = ?",
            (department_name,),
        ).fetchone()

    return dict(row)


def get_department_record(department_name: str) -> dict | None:
    department_name = normalize_department(department_name)
    if not department_name:
        return None

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM staff_status_departments WHERE department_name = ?",
            (department_name,),
        ).fetchone()
    return dict(row) if row else None


def list_enabled_departments() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM staff_status_departments
            WHERE is_enabled = 1
            ORDER BY department_name COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def sync_departments_from_users() -> list[dict]:
    departments = list_active_departments_from_users()
    for department_name in departments:
        ensure_department_record(department_name)

    return list_enabled_departments()


def seed_department_locations_if_empty(department_name: str, default_locations: list[str] | None = None):
    department_name = normalize_department(department_name)
    default_locations = default_locations or DEFAULT_LOCATIONS
    if not department_name:
        raise ValueError("department_name is required")

    now = utc_now_iso()
    with get_connection() as conn:
        existing_count = conn.execute(
            "SELECT COUNT(*) AS count FROM staff_status_locations WHERE department_name = ?",
            (department_name,),
        ).fetchone()["count"]

        if existing_count:
            return

        for sort_order, label in enumerate(default_locations, start=1):
            conn.execute(
                """
                INSERT INTO staff_status_locations (
                    department_name,
                    location_label,
                    sort_order,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (department_name, label, sort_order, now, now),
            )
        conn.commit()


def list_locations_for_department(department_name: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM staff_status_locations
            WHERE department_name = ?
              AND is_active = 1
            ORDER BY sort_order, location_label COLLATE NOCASE
            """,
            (department_name.strip(),),
        ).fetchall()
    return [dict(row) for row in rows]


def generate_kiosk_token() -> str:
    return secrets.token_urlsafe(32)


def rotate_kiosk_token(department_name: str) -> dict:
    department_name = normalize_department(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    token = generate_kiosk_token()
    now = utc_now_iso()

    ensure_department_record(department_name)

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE staff_status_departments
            SET kiosk_enabled = 1,
                kiosk_token = ?,
                kiosk_token_created_at = COALESCE(kiosk_token_created_at, ?),
                kiosk_token_rotated_at = ?,
                updated_at = ?
            WHERE department_name = ?
            """,
            (token, now, now, now, department_name),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM staff_status_departments WHERE department_name = ?",
            (department_name,),
        ).fetchone()
    return dict(row)


def get_department_by_kiosk_token(token: str) -> dict | None:
    token = normalize_text(token)
    if not token:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM staff_status_departments
            WHERE kiosk_enabled = 1
              AND kiosk_token = ?
              AND is_enabled = 1
            """,
            (token,),
        ).fetchone()
    return dict(row) if row else None


def _json_dump(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _json_load(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    try:
        value = json.loads(raw_value)
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _get_active_absence_for_user(user_id: int, on_date: date | None = None) -> dict | None:
    on_date = on_date or date.today()
    target = on_date.isoformat()

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM staff_status_absences
            WHERE user_id = ?
              AND is_active = 1
              AND start_date <= ?
              AND end_date >= ?
            ORDER BY start_date DESC, id DESC
            LIMIT 1
            """,
            (user_id, target, target),
        ).fetchone()
    return dict(row) if row else None


def get_board_rows_for_department(department_name: str) -> list[dict]:
    users = list_active_users_for_department(department_name)

    with get_connection() as conn:
        current_rows = conn.execute(
            """
            SELECT *
            FROM staff_status_current
            WHERE department_name = ?
            """,
            (department_name.strip(),),
        ).fetchall()

    current_map = {row["user_id"]: dict(row) for row in current_rows}
    board_rows = []

    for user in users:
        absence = _get_active_absence_for_user(user["id"])
        current = current_map.get(user["id"])

        if absence:
            board_rows.append(
                {
                    "user_id": user["id"],
                    "display_name": user["resolved_display_name"],
                    "department_name": department_name,
                    "display_status_label": absence["public_status_label"],
                    "location_labels": [],
                    "is_out_of_office": True,
                    "updated_at": absence["updated_at"] or absence["created_at"],
                }
            )
            continue

        if current:
            board_rows.append(
                {
                    "user_id": user["id"],
                    "display_name": user["resolved_display_name"],
                    "department_name": department_name,
                    "display_status_label": current["display_status_label"],
                    "location_labels": _json_load(current["location_labels_json"]),
                    "is_out_of_office": bool(current["is_out_of_office"]),
                    "updated_at": current["updated_at"],
                }
            )
            continue

        home_location = get_department_home_location(department_name)
        board_rows.append(
            {
                "user_id": user["id"],
                "display_name": user["resolved_display_name"],
                "department_name": department_name,
                "display_status_label": home_location,
                "location_labels": [home_location],
                "is_out_of_office": False,
                "updated_at": None,
            }
        )

    return board_rows

def rotate_board_token(department_name: str) -> dict:
    department_name = normalize_department(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    token = generate_kiosk_token()
    now = utc_now_iso()

    ensure_department_record(department_name)

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE staff_status_departments
            SET board_enabled = 1,
                board_token = ?,
                board_token_created_at = COALESCE(board_token_created_at, ?),
                board_token_rotated_at = ?,
                updated_at = ?
            WHERE department_name = ?
            """,
            (token, now, now, now, department_name),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM staff_status_departments WHERE department_name = ?",
            (department_name,),
        ).fetchone()

    return dict(row)


def get_department_by_board_token(token: str) -> dict | None:
    token = normalize_text(token)
    if not token:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM staff_status_departments
            WHERE board_enabled = 1
              AND board_token = ?
              AND is_enabled = 1
            """,
            (token,),
        ).fetchone()

    return dict(row) if row else None


def get_department_home_location(department_name: str) -> str:
    record = get_department_record(department_name)
    if record and normalize_text(record.get("home_location_label")):
        return record["home_location_label"]

    configured = normalize_text(get_setting(f"staff_status.department.{department_name}.home_location", ""))
    if configured:
        return configured

    return "Technology Office"


def update_user_status(
    *,
    user_id: int,
    department_name: str,
    location_labels: list[str],
    committed_by_user_id: int | None,
    committed_by_display_name: str | None,
    updated_by_source: str,
    source_ip: str | None = None,
    source_device: str | None = None,
):
    if not location_labels:
        raise ValueError("At least one location must be selected")

    department_name = normalize_department(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    now = utc_now_iso()
    display_status_label = ", ".join([label.strip() for label in location_labels if label.strip()])
    payload_json = _json_dump(location_labels)

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM staff_status_current WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE staff_status_current
                SET department_name = ?,
                    location_labels_json = ?,
                    display_status_label = ?,
                    is_out_of_office = 0,
                    updated_at = ?,
                    updated_by_user_id = ?,
                    updated_by_display_name = ?,
                    updated_by_source = ?
                WHERE user_id = ?
                """,
                (
                    department_name,
                    payload_json,
                    display_status_label,
                    now,
                    committed_by_user_id,
                    committed_by_display_name,
                    updated_by_source,
                    user_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO staff_status_current (
                    user_id,
                    department_name,
                    location_labels_json,
                    display_status_label,
                    is_out_of_office,
                    updated_at,
                    updated_by_user_id,
                    updated_by_display_name,
                    updated_by_source
                )
                VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    department_name,
                    payload_json,
                    display_status_label,
                    now,
                    committed_by_user_id,
                    committed_by_display_name,
                    updated_by_source,
                ),
            )

        conn.execute(
            """
            INSERT INTO staff_status_history (
                user_id,
                department_name,
                event_type,
                location_labels_json,
                private_status_type,
                public_status_label,
                committed_by_user_id,
                committed_by_display_name,
                committed_at,
                source_ip,
                source_device
            )
            VALUES (?, ?, 'location_update', ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                department_name,
                payload_json,
                display_status_label,
                committed_by_user_id,
                committed_by_display_name,
                now,
                source_ip,
                source_device,
            ),
        )
        conn.commit()


def create_absence(
    *,
    user_id: int,
    department_name: str,
    absence_type: str,
    start_date: str,
    end_date: str,
    note: str | None,
    created_by_user_id: int,
    created_by_display_name: str,
):
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO staff_status_absences (
                user_id,
                department_name,
                absence_type,
                public_status_label,
                start_date,
                end_date,
                note,
                created_by_user_id,
                created_by_display_name,
                created_at,
                updated_by_user_id,
                updated_by_display_name,
                updated_at,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 1)
            """,
            (
                user_id,
                department_name,
                absence_type,
                DEFAULT_PUBLIC_ABSENCE_LABEL,
                start_date,
                end_date,
                normalize_text(note),
                created_by_user_id,
                created_by_display_name,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO staff_status_history (
                user_id,
                department_name,
                event_type,
                location_labels_json,
                private_status_type,
                public_status_label,
                committed_by_user_id,
                committed_by_display_name,
                committed_at,
                source_ip,
                source_device
            )
            VALUES (?, ?, 'absence_override', NULL, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                user_id,
                department_name,
                absence_type,
                DEFAULT_PUBLIC_ABSENCE_LABEL,
                created_by_user_id,
                created_by_display_name,
                now,
            ),
        )
        conn.commit()

def upsert_department_settings(
    department_name: str,
    is_enabled: bool,
    home_location: str | None,
):
    department_name = normalize_department(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    now = utc_now_iso()
    normalized_home_location = normalize_text(home_location)

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM staff_status_departments
            WHERE department_name = ?
            """,
            (department_name,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE staff_status_departments
                SET is_enabled = ?,
                    home_location_label = ?,
                    updated_at = ?
                WHERE department_name = ?
                """,
                (
                    1 if is_enabled else 0,
                    normalized_home_location,
                    now,
                    department_name,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO staff_status_departments (
                    department_name,
                    is_enabled,
                    home_location_label,
                    kiosk_enabled,
                    kiosk_token,
                    kiosk_token_created_at,
                    kiosk_token_rotated_at,
                    board_enabled,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, 0, NULL, NULL, NULL, 1, ?, ?)
                """,
                (
                    department_name,
                    1 if is_enabled else 0,
                    normalized_home_location,
                    now,
                    now,
                ),
            )

        conn.commit()