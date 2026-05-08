import json, zoneinfo, secrets, csv, io
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from flask import current_app, url_for

from .db import get_connection
from modules.core.identity.identity_db import get_connection as get_identity_connection
from modules.core.settings.settings_service import get_setting

from tasks.events import publish_department_update

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

DEFAULT_PUBLIC_ABSENCE_LABEL = "Out of Office"
DEFAULT_LOCATIONS = [
    {"display_name": "East End Elementary", "short_name": "EEE"},
    {"display_name": "East End Middle", "short_name": "EEM"},
    {"display_name": "East End Intermediate", "short_name": "EEI"},
    {"display_name": "Technology Office", "short_name": "Technology Office"},
    {"display_name": "Sheridan High School", "short_name": "SHS"},
    {"display_name": "Sheridan Middle School", "short_name": "SMS"},
    {"display_name": "Sheridan Intermediate School", "short_name": "SIS"},
    {"display_name": "Sheridan Elementary School", "short_name": "SES"},
    {"display_name": "Central Office", "short_name": "Central Office"},
    {"display_name": "Annex", "short_name": "Annex"},
    {"display_name": "Jacket Health", "short_name": "Jacket Health"},
    {"display_name": "Alternative Learning Academy", "short_name": "ALA"},
    {"display_name": "Off Campus", "short_name": "Off Campus"},
]

def get_app_timezone() -> str:
    # Replace "general.timezone" below with your actual General settings key
    return get_setting("general.timezone", "America/Chicago") or "America/Chicago"

def format_board_timestamp(iso_ts: str | None) -> str:
    if not iso_ts:
        return "—"

    try:
        tz = zoneinfo.ZoneInfo(get_app_timezone())
        dt = datetime.fromisoformat(iso_ts)
        dt = dt.astimezone(tz)

        hour = dt.strftime("%I").lstrip("0") or "12"
        return f"{hour}:{dt.strftime('%M %p')}"
    except Exception:
        return "—"

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

        for sort_order, item in enumerate(default_locations, start=1):
            conn.execute(
                """
                INSERT INTO staff_status_locations (
                    department_name,
                    location_label,
                    display_name,
                    short_name,
                    sort_order,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    department_name,
                    item["short_name"],
                    item.get("display_name"),
                    item.get("short_name"),
                    sort_order,
                    now,
                    now,
                ),
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
                    "updated_at": format_board_timestamp(
                        current["updated_at"] if current else absence["updated_at"] or absence["created_at"]
                    ),
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
                    "updated_at": format_board_timestamp(current["updated_at"]),
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

    configured = normalize_text(
        get_setting(f"staff_status.department.{department_name}.home_location", "")
    )
    if configured:
        return configured

    return "Not Configured"


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
    duration_mode: str,
    days_value: float | None,
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
                duration_mode,
                days_value,
                note,
                created_by_user_id,
                created_by_display_name,
                created_at,
                updated_by_user_id,
                updated_by_display_name,
                updated_at,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 1)
            """,
            (
                user_id,
                department_name,
                absence_type,
                DEFAULT_PUBLIC_ABSENCE_LABEL,
                start_date,
                end_date,
                duration_mode,
                days_value,
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
        
def update_absence(
    *,
    absence_id: int,
    absence_type: str,
    start_date: str,
    end_date: str,
    duration_mode: str,
    days_value: float | None,
    note: str | None,
    updated_by_user_id: int,
    updated_by_display_name: str,
):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE staff_status_absences
            SET
                absence_type = ?,
                start_date = ?,
                end_date = ?,
                duration_mode = ?,
                days_value = ?,
                note = ?,
                updated_by_user_id = ?,
                updated_by_display_name = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                absence_type,
                start_date,
                end_date,
                duration_mode,
                days_value,
                normalize_text(note),
                updated_by_user_id,
                updated_by_display_name,
                now,
                absence_id,
            ),
        )
        conn.commit()
        
def delete_absence(
    *,
    absence_id: int,
    updated_by_user_id: int,
    updated_by_display_name: str,
):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE staff_status_absences
            SET
                is_active = 0,
                updated_by_user_id = ?,
                updated_by_display_name = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                updated_by_user_id,
                updated_by_display_name,
                now,
                absence_id,
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
        
def reset_department_statuses(department_name: str):
    department_name = normalize_department(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    users = list_active_users_for_department(department_name)
    home_location = get_department_home_location(department_name)
    now = utc_now_iso()
    payload_json = _json_dump([home_location])

    print(f"[tasks] reset department={department_name} users={len(users)} home_location={home_location}")

    with get_connection() as conn:
        for user in users:
            print(f"[tasks] resetting user_id={user['id']} display_name={user['resolved_display_name']}")

            existing = conn.execute(
                """
                SELECT id
                FROM staff_status_current
                WHERE user_id = ?
                """,
                (user["id"],),
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
                        updated_by_user_id = NULL,
                        updated_by_display_name = ?,
                        updated_by_source = ?
                    WHERE user_id = ?
                    """,
                    (
                        department_name,
                        payload_json,
                        home_location,
                        now,
                        "System Daily Reset",
                        "system_reset",
                        user["id"],
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
                    VALUES (?, ?, ?, ?, 0, ?, NULL, ?, ?)
                    """,
                    (
                        user["id"],
                        department_name,
                        payload_json,
                        home_location,
                        now,
                        "System Daily Reset",
                        "system_reset",
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
                VALUES (?, ?, 'reset', ?, NULL, ?, NULL, ?, ?, NULL, NULL)
                """,
                (
                    user["id"],
                    department_name,
                    payload_json,
                    home_location,
                    "System Daily Reset",
                    now,
                ),
            )

        conn.commit()
        
    publish_department_update(department_name)

def reset_all_enabled_departments():
    departments = list_enabled_departments()
    print(f"[tasks] enabled_departments={len(departments)}")

    for department in departments:
        print(f"[tasks] running reset for {department['department_name']}")
        reset_department_statuses(department["department_name"])
        
def list_locations_for_department_admin(department_name: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM staff_status_locations
            WHERE department_name = ?
            ORDER BY sort_order, location_label COLLATE NOCASE
            """,
            (department_name.strip(),),
        ).fetchall()
    return [dict(row) for row in rows]


def create_location(
    department_name: str,
    display_name: str | None,
    short_name: str | None,
    sort_order: int | None,
):
    department_name = normalize_department(department_name)
    display_name = normalize_text(display_name)
    short_name = normalize_text(short_name)

    if not department_name:
        raise ValueError("department_name is required")
    if not short_name:
        raise ValueError("short_name is required")

    now = utc_now_iso()
    sort_value = sort_order if sort_order is not None else 0
    location_label = short_name

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO staff_status_locations (
                department_name,
                location_label,
                display_name,
                short_name,
                sort_order,
                is_active,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                department_name,
                location_label,
                display_name or short_name,
                short_name,
                sort_value,
                now,
                now,
            ),
        )
        conn.commit()


def update_location(
    location_id: int,
    display_name: str | None,
    short_name: str | None,
    sort_order: int | None,
    is_active: bool,
    ):
    display_name = normalize_text(display_name)
    short_name = normalize_text(short_name)

    if not short_name:
        raise ValueError("short_name is required")

    now = utc_now_iso()
    sort_value = sort_order if sort_order is not None else 0
    location_label = short_name

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE staff_status_locations
            SET location_label = ?,
                display_name = ?,
                short_name = ?,
                sort_order = ?,
                is_active = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                location_label,
                display_name or short_name,
                short_name,
                sort_value,
                1 if is_active else 0,
                now,
                location_id,
            ),
        )
        conn.commit()


def delete_location(location_id: int):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM staff_status_locations WHERE id = ?",
            (location_id,),
        )
        conn.commit()

def reorder_locations_for_department(
    *,
    department_name: str,
    location_ids: list[int],
):
    department_name = normalize_department(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    now = utc_now_iso()

    with get_connection() as conn:
        valid_rows = conn.execute(
            """
            SELECT id
            FROM staff_status_locations
            WHERE department_name = ?
            """,
            (department_name,),
        ).fetchall()

        valid_ids = {row["id"] for row in valid_rows}

        filtered_location_ids = [
            location_id
            for location_id in location_ids
            if location_id in valid_ids
        ]

        for sort_order, location_id in enumerate(filtered_location_ids, start=1):
            conn.execute(
                """
                UPDATE staff_status_locations
                SET sort_order = ?,
                    updated_at = ?
                WHERE id = ?
                  AND department_name = ?
                """,
                (sort_order, now, location_id, department_name),
            )

        conn.commit()
        
def list_recent_absences_for_department(
    department_name: str,
    limit: int = 50,
    sort_by: str = "start_date",
    sort_dir: str = "desc",
    view: str = "active",
    absence_types: list[str] | None = None,
    user_ids: list[str] | None = None,
) -> list[dict]:
    department_name = normalize_department(department_name)
    if not department_name:
        return []

    allowed_sort_map = {
        "user": "user_id",
        "absence_type": "absence_type",
        "start_date": "start_date",
        "end_date": "end_date",
        "days_value": "days_value",
        "created_at": "created_at",
    }

    order_column = allowed_sort_map.get(sort_by, "start_date")
    order_direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

    today = date.today().isoformat()

    where_clauses = ["department_name = ?"]
    params: list = [department_name]

    if view == "today":
        where_clauses.append("is_active = 1")
        where_clauses.append("start_date <= ?")
        where_clauses.append("end_date >= ?")
        params.extend([today, today])
    elif view == "upcoming":
        where_clauses.append("is_active = 1")
        where_clauses.append("start_date > ?")
        params.append(today)
        order_column = "start_date"
        order_direction = "ASC"
    elif view == "all":
        pass
    else:
        where_clauses.append("is_active = 1")

    normalized_absence_types = [
        item.lower()
        for item in (absence_types or [])
        if normalize_text(item)
    ]
    if normalized_absence_types:
        placeholders = ",".join(["?"] * len(normalized_absence_types))
        where_clauses.append(f"absence_type IN ({placeholders})")
        params.extend(normalized_absence_types)

    normalized_user_ids: list[int] = []
    for item in (user_ids or []):
        try:
            normalized_user_ids.append(int(item))
        except ValueError:
            continue

    if normalized_user_ids:
        placeholders = ",".join(["?"] * len(normalized_user_ids))
        where_clauses.append(f"user_id IN ({placeholders})")
        params.extend(normalized_user_ids)

    where_sql = " AND ".join(where_clauses)

    query = f"""
        SELECT *
        FROM staff_status_absences
        WHERE {where_sql}
        ORDER BY {order_column} {order_direction}, id DESC
        LIMIT ?
    """

    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    absences = [dict(row) for row in rows]

    user_ids_from_rows = [row["user_id"] for row in absences if row.get("user_id")]
    user_map = {}

    if user_ids_from_rows:
        unique_user_ids = list(dict.fromkeys(user_ids_from_rows))
        placeholders = ",".join(["?"] * len(unique_user_ids))

        with get_identity_connection() as conn:
            user_rows = conn.execute(
                f"""
                SELECT *
                FROM users
                WHERE id IN ({placeholders})
                """,
                unique_user_ids,
            ).fetchall()

        user_map = {row["id"]: dict(row) for row in user_rows}

    for row in absences:
        user = user_map.get(row["user_id"])
        row["user_display_name"] = (
            build_display_name(user) if user else f"User {row['user_id']}"
        )

    return absences

def build_public_url(endpoint: str, **values) -> str:
    path = url_for(endpoint, _external=False, **values)

    base = (get_setting("general.public_base_url", "") or "").rstrip("/")

    if base:
        return f"{base}{path}"

    # fallback ONLY if not configured
    return url_for(endpoint, _external=True, **values)

OVERVIEW_RANGE_OPTIONS = {
    "1d": {"label": "Today", "days": 1},
    "7d": {"label": "Past 7 Days", "days": 7},
    "14d": {"label": "Past 14 Days", "days": 14},
    "30d": {"label": "Past 30 Days", "days": 30},
    "90d": {"label": "Past 90 Days", "days": 90},
    "365d": {"label": "Past 365 Days", "days": 365},
}


def normalize_overview_range(range_key: str | None) -> str:
    value = (range_key or "").strip().lower()
    return value if value in OVERVIEW_RANGE_OPTIONS else "30d"

def get_overview_range_options() -> list[dict]:
    return [
        {"key": key, "label": meta["label"]}
        for key, meta in OVERVIEW_RANGE_OPTIONS.items()
    ]

def _get_overview_range_start(range_key: str) -> datetime:
    normalized = normalize_overview_range(range_key)
    now = datetime.now(timezone.utc)

    if normalized == "1d":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    days = OVERVIEW_RANGE_OPTIONS[normalized]["days"]
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    return start


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

def _iter_location_labels(raw_value: str | None) -> list[str]:
    labels = []
    for item in _json_load(raw_value):
        normalized = normalize_text(item)
        if normalized:
            labels.append(normalized)
    return labels


OVERVIEW_RANGE_OPTIONS = {
    "1d": {"label": "Today", "days": 1},
    "7d": {"label": "Past 7 Days", "days": 7},
    "14d": {"label": "Past 14 Days", "days": 14},
    "30d": {"label": "Past 30 Days", "days": 30},
    "90d": {"label": "Past 90 Days", "days": 90},
    "365d": {"label": "Past 365 Days", "days": 365},
}


def normalize_overview_range(range_key: str | None) -> str:
    value = (range_key or "").strip().lower()
    return value if value in OVERVIEW_RANGE_OPTIONS else "30d"


def get_overview_range_options() -> list[dict]:
    return [
        {"key": key, "label": meta["label"]}
        for key, meta in OVERVIEW_RANGE_OPTIONS.items()
    ]


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _get_overview_range_start(range_key: str) -> datetime:
    normalized = normalize_overview_range(range_key)
    app_tz = zoneinfo.ZoneInfo(get_app_timezone())
    now_local = datetime.now(app_tz)
    start_of_today_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if normalized == "1d":
        return start_of_today_local.astimezone(timezone.utc)

    days = OVERVIEW_RANGE_OPTIONS[normalized]["days"]
    start_local = start_of_today_local - timedelta(days=days - 1)
    return start_local.astimezone(timezone.utc)


def _iter_location_labels(raw_value: str | None) -> list[str]:
    labels = []
    for item in _json_load(raw_value):
        normalized = normalize_text(item)
        if normalized:
            labels.append(normalized)
    return labels


def get_department_overview_analytics(
    department_name: str,
    range_key: str = "30d",
) -> dict:
    department_name = normalize_department(department_name)
    normalized_range = normalize_overview_range(range_key)

    empty_result = {
        "range_key": normalized_range,
        "summary": {
            "check_ins": 0,
            "staff_in_office": 0,
            "top_location_label": None,
            "top_location_count": 0,
        },
        "location_distribution": [],
        "top_locations": [],
        "trend_points": [],
        "debug": {
            "all_rows_in_range": 0,
            "location_update_rows": 0,
            "absence_override_rows": 0,
            "reset_rows": 0,
        },
    }

    if not department_name:
        return empty_result

    range_start = _get_overview_range_start(normalized_range)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM staff_status_history
            WHERE department_name = ?
            ORDER BY committed_at DESC, id DESC
            """,
            (department_name,),
        ).fetchall()

    filtered_rows: list[dict] = []
    for row in rows:
        row_dict = dict(row)
        committed_at = _parse_iso_datetime(row_dict.get("committed_at"))
        if not committed_at:
            continue
        if committed_at >= range_start:
            row_dict["_committed_at_utc"] = committed_at
            filtered_rows.append(row_dict)

    location_update_rows = [
        row for row in filtered_rows if row.get("event_type") == "location_update"
    ]
    absence_rows = [
        row for row in filtered_rows if row.get("event_type") == "absence_override"
    ]
    reset_rows = [
        row for row in filtered_rows if row.get("event_type") == "reset"
    ]
    staff_in_office = get_staff_in_office_count(department_name)
    location_counter: Counter[str] = Counter()
    for row in location_update_rows:
        for label in _iter_location_labels(row.get("location_labels_json")):
            location_counter[label] += 1

    top_locations = [
        {"label": label, "count": count}
        for label, count in location_counter.most_common(5)
    ]

    location_distribution = [
        {"label": label, "count": count}
        for label, count in location_counter.most_common()
    ]

    top_location_label = None
    top_location_count = 0
    if location_distribution:
        top_location_label = location_distribution[0]["label"]
        top_location_count = location_distribution[0]["count"]

    trend_counter: Counter[str] = Counter()
    app_tz = zoneinfo.ZoneInfo(get_app_timezone())

    for row in location_update_rows:
        committed_at = row.get("_committed_at_utc")
        if not committed_at:
            continue

        local_dt = committed_at.astimezone(app_tz)

        if normalized_range == "365d":
            bucket = local_dt.strftime("%Y-%m")
        else:
            bucket = local_dt.strftime("%Y-%m-%d")

        trend_counter[bucket] += 1

    trend_points = [
        {"bucket": bucket, "count": trend_counter[bucket]}
        for bucket in sorted(trend_counter.keys())
    ]

    return {
        "range_key": normalized_range,
        "summary": {
            "check_ins": len(location_update_rows),
            "staff_in_office": staff_in_office,
            "top_location_label": top_location_label,
            "top_location_count": top_location_count,
        },
        "location_distribution": location_distribution,
        "top_locations": top_locations,
        "trend_points": trend_points,
        "debug": {
            "all_rows_in_range": len(filtered_rows),
            "location_update_rows": len(location_update_rows),
            "absence_override_rows": len(absence_rows),
            "reset_rows": len(reset_rows),
        },
    }
    
def get_staff_in_office_count(department_name: str) -> int:
    department_name = normalize_department(department_name)
    if not department_name:
        return 0

    home_location = normalize_text(get_department_home_location(department_name))
    if not home_location:
        return 0

    board_rows = get_board_rows_for_department(department_name)

    count = 0
    for row in board_rows:
        if row.get("is_out_of_office"):
            continue

        location_labels = row.get("location_labels") or []
        normalized_labels = {
            normalize_text(label)
            for label in location_labels
            if normalize_text(label)
        }

        if home_location in normalized_labels:
            count += 1

    return count

ABSENCE_DURATION_LOOKUP = {
    "quarter_day": 0.25,
    "half_day": 0.5,
    "three_quarter_day": 0.75,
    "full_day": 1.0,
    "summer_2_hours": 0.25,
    "summer_4_hours": 0.5,
    "summer_6_hours": 0.75,
    "summer_8_hours": 1.0,
    "summer_full_day": 1.25,
}

ABSENCE_DURATION_OPTIONS = [
    {"value": "quarter_day", "label": "2 hours"},
    {"value": "half_day", "label": "4 hours"},
    {"value": "three_quarter_day", "label": "6 hours"},
    {"value": "full_day", "label": "8 hours / Full regular day"},
    {"value": "summer_2_hours", "label": "Summer - 2 hours"},
    {"value": "summer_4_hours", "label": "Summer - 4 hours"},
    {"value": "summer_6_hours", "label": "Summer - 6 hours"},
    {"value": "summer_8_hours", "label": "Summer - 8 hours"},
    {"value": "summer_full_day", "label": "Summer full day - 10 hours / 1.25 days"},
    {"value": "multi_day", "label": "Multiple Days"},
]


def resolve_absence_duration(form):
    duration_mode = (form.get("duration_mode") or "").strip()
    days_value_raw = (form.get("days_value") or "").strip()

    if duration_mode == "multi_day":
        try:
            days_value = float(days_value_raw)
        except ValueError:
            days_value = None
        end_date = (form.get("end_date") or "").strip()
    else:
        days_value = ABSENCE_DURATION_LOOKUP.get(duration_mode)
        end_date = (form.get("start_date") or "").strip()

    return duration_mode, days_value, end_date


def get_absence_duration_label(duration_mode: str | None) -> str:
    labels = {
        item["value"]: item["label"]
        for item in ABSENCE_DURATION_OPTIONS
    }
    return labels.get(duration_mode or "", (duration_mode or "").replace("_", " ").title() or "—")


def absence_days_to_hours(days_value) -> str:
    if days_value is None:
        return "—"

    try:
        hours = float(days_value) * 8
    except (TypeError, ValueError):
        return "—"

    return str(int(hours)) if hours.is_integer() else str(hours)


def _get_absence_user_display_names(user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}

    placeholders = ",".join(["?"] * len(user_ids))

    with get_identity_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, display_name, first_name, last_name, email
            FROM users
            WHERE id IN ({placeholders})
            """,
            user_ids,
        ).fetchall()

    names = {}
    for row in rows:
        user = dict(row)
        names[int(user["id"])] = build_display_name(user)

    return names


def list_absences_for_department(
    *,
    department_name: str,
    timing: str = "upcoming",
    absence_types: list[str] | None = None,
    user_ids: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    department_name = normalize_department(department_name)
    if not department_name:
        return []

    today = date.today().isoformat()

    where_clauses = [
        "department_name = ?",
        "is_active = 1",
    ]
    params: list = [department_name]

    if timing == "upcoming":
        where_clauses.append("start_date >= ?")
        params.append(today)
        order_sql = "start_date ASC, end_date ASC, id ASC"
    elif timing == "past":
        where_clauses.append("end_date < ?")
        params.append(today)
        order_sql = "end_date DESC, start_date DESC, id DESC"
    else:
        order_sql = "start_date DESC, end_date DESC, id DESC"

    cleaned_types = [
        item.strip().lower()
        for item in (absence_types or [])
        if item and item.strip()
    ]

    if cleaned_types:
        placeholders = ",".join(["?"] * len(cleaned_types))
        where_clauses.append(f"absence_type IN ({placeholders})")
        params.extend(cleaned_types)

    cleaned_user_ids = []
    for item in user_ids or []:
        try:
            cleaned_user_ids.append(int(item))
        except (TypeError, ValueError):
            continue

    if cleaned_user_ids:
        placeholders = ",".join(["?"] * len(cleaned_user_ids))
        where_clauses.append(f"user_id IN ({placeholders})")
        params.extend(cleaned_user_ids)

    if start_date:
        where_clauses.append("end_date >= ?")
        params.append(start_date)

    if end_date:
        where_clauses.append("start_date <= ?")
        params.append(end_date)

    sql = f"""
        SELECT *
        FROM staff_status_absences
        WHERE {" AND ".join(where_clauses)}
        ORDER BY {order_sql}
    """

    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))

    with get_connection() as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

    user_names = _get_absence_user_display_names(
        list({int(row["user_id"]) for row in rows if row.get("user_id")})
    )

    for row in rows:
        row["user_display_name"] = user_names.get(int(row["user_id"]), f"User {row['user_id']}")
        row["duration_label"] = get_absence_duration_label(row.get("duration_mode"))
        row["hours_value"] = absence_days_to_hours(row.get("days_value"))

    return rows


def build_absence_csv_export(
    *,
    department_name: str,
    timing: str,
    absence_types: list[str] | None,
    user_ids: list[str] | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, str]:
    rows = list_absences_for_department(
        department_name=department_name,
        timing=timing,
        absence_types=absence_types,
        user_ids=user_ids,
        start_date=start_date,
        end_date=end_date,
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "User",
        "Absence Type",
        "Start Date",
        "End Date",
        "Duration",
        "Days",
        "Hours",
        "Note",
        "Entered By",
        "Created At",
    ])

    for item in rows:
        writer.writerow([
            item.get("user_display_name") or f"User {item.get('user_id')}",
            item.get("absence_type") or "",
            item.get("start_date") or "",
            item.get("end_date") or "",
            item.get("duration_label") or "",
            item.get("days_value") if item.get("days_value") is not None else "",
            item.get("hours_value") or "",
            item.get("note") or "",
            item.get("created_by_display_name") or "",
            item.get("created_at") or "",
        ])

    safe_department = department_name.lower().replace(" ", "-")
    filename = f"{safe_department}-absences.csv"

    return output.getvalue(), filename

def build_absence_pdf_export(
    *,
    department_name: str,
    timing: str,
    absence_types: list[str] | None,
    user_ids: list[str] | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[bytes, str]:
    rows = list_absences_for_department(
        department_name=department_name,
        timing=timing,
        absence_types=absence_types,
        user_ids=user_ids,
        start_date=start_date,
        end_date=end_date,
    )

    rows = sorted(
        rows,
        key=lambda item: (
            item.get("start_date") or "",
            item.get("end_date") or "",
            item.get("user_display_name") or "",
        ),
    )

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=24,
        leftMargin=24,
        topMargin=24,
        bottomMargin=24,
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"{department_name} Absence Report", styles["Title"]))

    report_parameters = []

    if start_date or end_date:
        report_parameters.append(
            f"Date Range: {start_date or 'Any'} to {end_date or 'Any'}"
        )
    else:
        report_parameters.append("Date Range: Any")

    if absence_types:
        report_parameters.append(
            "Absence Type: " + ", ".join([item.title() for item in absence_types])
        )
    else:
        report_parameters.append("Absence Type: All")

    cleaned_user_ids = []
    for item in user_ids or []:
        try:
            cleaned_user_ids.append(int(item))
        except (TypeError, ValueError):
            continue

    if cleaned_user_ids:
        user_names = _get_absence_user_display_names(cleaned_user_ids)
        selected_users = [
            user_names.get(user_id, f"User {user_id}")
            for user_id in cleaned_user_ids
        ]
        report_parameters.append("Users: " + ", ".join(selected_users))
    else:
        report_parameters.append("Users: All")

    if timing == "upcoming":
        report_parameters.append("Timing: Upcoming Absences")
    elif timing == "past":
        report_parameters.append("Timing: Past Absences")
    else:
        report_parameters.append("Timing: Upcoming and Past Absences")

    story.append(Paragraph("Report Parameters", styles["Heading2"]))

    for parameter in report_parameters:
        story.append(Paragraph(parameter, styles["Normal"]))

    story.append(Spacer(1, 12))

    data = [[
        "User",
        "Type",
        "Start",
        "End",
        "Duration",
        "Days",
        "Hours",
        "Entered By",
    ]]

    for item in rows:
        data.append([
            item.get("user_display_name") or f"User {item.get('user_id')}",
            (item.get("absence_type") or "").title(),
            item.get("start_date") or "",
            item.get("end_date") or "",
            item.get("duration_label") or "",
            str(item.get("days_value") or ""),
            item.get("hours_value") or "",
            item.get("created_by_display_name") or "",
        ])

    if len(data) == 1:
        data.append(["No matching absences", "", "", "", "", "", "", ""])

    table = Table(
        data,
        repeatRows=1,
        colWidths=[120, 70, 70, 70, 150, 45, 45, 120],
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(table)
    doc.build(story)

    safe_department = department_name.lower().replace(" ", "-")
    filename = f"{safe_department}-absences.pdf"

    return buffer.getvalue(), filename

def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_school_year_settings() -> dict:
    start_month = _to_int(get_setting("general.school_year.start_month", 7), 7)
    start_day = _to_int(get_setting("general.school_year.start_day", 1), 1)
    end_month = _to_int(get_setting("general.school_year.end_month", 6), 6)
    end_day = _to_int(get_setting("general.school_year.end_day", 30), 30)
    reminder_days = _to_int(get_setting("general.school_year.rollover_reminder_days", 45), 45)

    return {
        "start_month": start_month,
        "start_day": start_day,
        "end_month": end_month,
        "end_day": end_day,
        "rollover_reminder_days": reminder_days,
    }


def get_current_school_year_range(today: date | None = None) -> dict:
    today = today or date.today()
    settings = get_school_year_settings()

    start_month = settings["start_month"]
    start_day = settings["start_day"]
    end_month = settings["end_month"]
    end_day = settings["end_day"]

    school_year_start_this_year = date(today.year, start_month, start_day)

    if today >= school_year_start_this_year:
        start_year = today.year
        end_year = today.year + 1 if (end_month, end_day) < (start_month, start_day) else today.year
    else:
        start_year = today.year - 1
        end_year = today.year if (end_month, end_day) < (start_month, start_day) else today.year - 1

    start_date = date(start_year, start_month, start_day)
    end_date = date(end_year, end_month, end_day)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "start_date_iso": start_date.isoformat(),
        "end_date_iso": end_date.isoformat(),
        "label": f"{start_date.year}-{end_date.year}",
    }


def get_school_year_rollover_reminder(today: date | None = None) -> dict:
    today = today or date.today()
    school_year = get_current_school_year_range(today)
    settings = get_school_year_settings()

    days_until_end = (school_year["end_date"] - today).days
    reminder_days = settings["rollover_reminder_days"]

    return {
        "show": 0 <= days_until_end <= reminder_days,
        "days_until_end": days_until_end,
        "reminder_days": reminder_days,
        "school_year": school_year,
        "steps": [
            "Review current school year absence records for accuracy.",
            "Export CSV/PDF absence reports for archive records.",
            "Confirm staff allowances for the next school year.",
            "Update the school year settings if next year uses different dates.",
            "Use the new school year range for future absence tracking.",
        ],
    }

def get_department_absence_usage_summary(
    *,
    department_name: str,
) -> dict:
    school_year = get_current_school_year_range()

    users = list_active_users_for_department(department_name)

    usage_map = {}

    for user in users:
        user_id = int(user["id"])
        usage_map[user_id] = {
            "user_id": user_id,
            "user_display_name": user["resolved_display_name"],
            "school_year_label": school_year["label"],
            "types": {
                "sick": 0.0,
                "personal": 0.0,
                "vacation": 0.0,
                "other": 0.0,
            },
            "total_used_days": 0.0,
        }

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                user_id,
                absence_type,
                SUM(COALESCE(days_value, 0)) AS used_days
            FROM staff_status_absences
            WHERE department_name = ?
              AND is_active = 1
              AND start_date <= ?
              AND end_date >= ?
            GROUP BY user_id, absence_type
            """,
            (
                department_name.strip(),
                school_year["end_date_iso"],
                school_year["start_date_iso"],
            ),
        ).fetchall()

    for row in rows:
        user_id = int(row["user_id"])
        absence_type = (row["absence_type"] or "other").lower()
        used_days = float(row["used_days"] or 0)

        if user_id not in usage_map:
            continue

        if absence_type not in usage_map[user_id]["types"]:
            usage_map[user_id]["types"][absence_type] = 0.0

        usage_map[user_id]["types"][absence_type] = used_days
        usage_map[user_id]["total_used_days"] += used_days

    return {
        "school_year": school_year,
        "rows": sorted(
            usage_map.values(),
            key=lambda item: item["user_display_name"].lower(),
        ),
    }