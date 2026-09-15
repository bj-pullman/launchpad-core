import calendar
import json, zoneinfo, secrets, csv, io
import sqlite3
from urllib.parse import quote
from collections import Counter
from datetime import date, datetime, time, timezone, timedelta
from html import escape
from flask import current_app, url_for

from .db import get_connection
from modules.core.identity.identity_db import get_connection as get_identity_connection
from modules.core.identity.user_service import get_user_by_email, get_user_by_id
from modules.core.mail.service import send_mail
from modules.core.settings.settings_service import get_setting, set_setting, get_bool_setting

from tasks.events import publish_department_update

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak

DEFAULT_PUBLIC_ABSENCE_LABEL = "Out of Office"
DEFAULT_ABSENCE_APPROVAL_MANAGER_EMAIL = "bjpullman@sheridanschools.org"
ABSENCE_FORM_SETTING_PREFIX = "staff_status.absence_form"
ABSENCE_NOTIFICATION_SETTING_PREFIX = "staff_status.notifications"
VALID_PENDING_ABSENCE_STATUSES = {"pending", "approved", "rejected"}
ABSENCE_TYPES = ["sick", "vacation", "personal", "other"]
ABSENCE_TABLE_SORT_KEYS = {
    "user",
    "type",
    "start",
    "end",
    "time",
    "duration",
    "days",
    "hours",
    "entered_by",
    "created",
}
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
        return "N/A"

    try:
        tz = zoneinfo.ZoneInfo(get_app_timezone())
        dt = datetime.fromisoformat(iso_ts)
        dt = dt.astimezone(tz)

        hour = dt.strftime("%I").lstrip("0") or "12"
        return f"{hour}:{dt.strftime('%M %p')}"
    except Exception:
        return "N/A"

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_department(value: str | None) -> str | None:
    return normalize_text(value)


class StaffStatusValidationError(ValueError):
    pass


class PendingAbsenceRequestStateError(ValueError):
    pass


def get_app_zoneinfo() -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(get_app_timezone())
    except Exception:
        return zoneinfo.ZoneInfo("America/Chicago")


def get_local_now() -> datetime:
    return datetime.now(get_app_zoneinfo())


def format_friendly_date(value: str | date | None, include_weekday: bool = True) -> str:
    parsed = value if isinstance(value, date) else parse_iso_date(value)
    if not parsed:
        return "N/A"
    pattern = "%A, %B %d, %Y" if include_weekday else "%B %d, %Y"
    return parsed.strftime(pattern).replace(" 0", " ")


def format_friendly_date_range(start_value: str | None, end_value: str | None) -> str:
    start = parse_iso_date(start_value)
    end = parse_iso_date(end_value) or start
    if not start:
        return "N/A"
    if not end or end == start:
        return format_friendly_date(start)
    if start.year == end.year:
        start_label = start.strftime("%A, %B %d").replace(" 0", " ")
        end_label = end.strftime("%A, %B %d, %Y").replace(" 0", " ")
        return f"{start_label} – {end_label}"
    return f"{format_friendly_date(start)} – {format_friendly_date(end)}"


def format_friendly_timestamp(value: str | datetime | None) -> str:
    if not value:
        return "N/A"
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local_value = parsed.astimezone(get_app_zoneinfo())
        return local_value.strftime("%B %d, %Y at %I:%M %p").replace(" 0", " ")
    except (TypeError, ValueError):
        return "N/A"


def _normalize_local_datetime(value: datetime | None = None) -> datetime:
    tz = get_app_zoneinfo()
    if value is None:
        return datetime.now(tz)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def parse_iso_date(value: str | None) -> date | None:
    value = normalize_text(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def normalize_start_time(value: str | None) -> str | None:
    value = normalize_text(value)
    if not value:
        return None

    for pattern in ("%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            parsed = datetime.strptime(value.upper(), pattern).time()
            return parsed.strftime("%H:%M")
        except ValueError:
            continue

    return None


def format_start_time(start_time: str | None) -> str:
    normalized = normalize_start_time(start_time)
    if not normalized:
        return "All day"

    parsed = datetime.strptime(normalized, "%H:%M").time()
    return parsed.strftime("%I:%M %p").lstrip("0")


def absence_duration_hours(days_value) -> float | None:
    if days_value is None:
        return None
    try:
        return float(days_value) * 8
    except (TypeError, ValueError):
        return None


def is_timed_absence_mode(duration_mode: str | None) -> bool:
    return (duration_mode or "").strip() in {
        "quarter_day",
        "half_day",
        "three_quarter_day",
        "summer_2_hours",
        "summer_4_hours",
        "summer_6_hours",
    }


def validate_absence_payload(
    *,
    user_id: int,
    department_name: str,
    absence_type: str,
    start_date: str,
    end_date: str | None,
    duration_mode: str,
    days_value: float | None,
    start_time: str | None,
) -> dict:
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        raise StaffStatusValidationError("A valid staff member is required.")

    normalized_department = normalize_department(department_name)
    if not normalized_department:
        raise StaffStatusValidationError("Department is required.")

    normalized_type = (absence_type or "").strip().lower()
    if normalized_type not in ABSENCE_TYPES:
        raise StaffStatusValidationError("A valid absence type is required.")

    normalized_duration = (duration_mode or "").strip()
    allowed_duration_modes = {
        option["value"]
        for option in ABSENCE_DURATION_OPTIONS
    }
    if normalized_duration not in allowed_duration_modes:
        raise StaffStatusValidationError("A valid duration is required.")

    parsed_start = parse_iso_date(start_date)
    if not parsed_start:
        raise StaffStatusValidationError("A valid start date is required.")

    parsed_end = parse_iso_date(end_date)
    if not parsed_end:
        parsed_end = parsed_start

    if parsed_end < parsed_start:
        raise StaffStatusValidationError("End date cannot be before start date.")

    if normalized_duration == "multi_day":
        try:
            normalized_days = float(days_value)
        except (TypeError, ValueError):
            raise StaffStatusValidationError("Total days is required for multiple-day absences.")

        if normalized_days <= 0:
            raise StaffStatusValidationError("Total days must be greater than zero.")
    else:
        normalized_days = ABSENCE_DURATION_LOOKUP.get(normalized_duration)
        parsed_end = parsed_start

    normalized_start_time = normalize_start_time(start_time)
    if start_time and not normalized_start_time:
        raise StaffStatusValidationError("Start time must be a valid time.")

    if is_timed_absence_mode(normalized_duration) and not normalized_start_time:
        raise StaffStatusValidationError("Start time is required for partial-day absences.")

    return {
        "user_id": normalized_user_id,
        "department_name": normalized_department,
        "absence_type": normalized_type,
        "start_date": parsed_start.isoformat(),
        "end_date": parsed_end.isoformat(),
        "duration_mode": normalized_duration,
        "days_value": normalized_days,
        "start_time": normalized_start_time,
    }


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


def list_staff_status_departments() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM staff_status_departments
            ORDER BY department_name COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def set_department_staff_status_enabled(department_name: str, enabled: bool) -> None:
    department_name = normalize_department(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    ensure_department_record(department_name)

    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE staff_status_departments
            SET is_enabled = ?,
                updated_at = ?
            WHERE department_name = ?
            """,
            (1 if enabled else 0, now, department_name),
        )
        conn.commit()


def migrate_legacy_enabled_departments_setting() -> None:
    if get_setting("staff_status.enabled_departments.migrated_at", None):
        return

    legacy_value = get_setting("staff_status.enabled_departments", None)
    if not legacy_value:
        return

    enabled_names = {
        item.strip()
        for item in str(legacy_value).split(",")
        if item.strip()
    }
    if not enabled_names:
        return

    sync_departments_from_users()

    for department in list_staff_status_departments():
        department_name = department["department_name"]
        set_department_staff_status_enabled(
            department_name,
            department_name in enabled_names,
        )

    set_setting("staff_status.enabled_departments.migrated_at", utc_now_iso())


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


def _format_time_value(value: time) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _local_datetime_for_date_time(date_value: date, start_time: str) -> datetime:
    parsed_time = datetime.strptime(start_time, "%H:%M").time()
    return datetime.combine(date_value, parsed_time, tzinfo=get_app_zoneinfo())


def get_absence_duration_hours(
    duration_mode: str | None,
    days_value,
) -> float | None:
    mode = (duration_mode or "").strip()
    if mode != "multi_day" and mode in ABSENCE_DURATION_LOOKUP:
        return ABSENCE_DURATION_LOOKUP[mode] * 8

    return absence_duration_hours(days_value)


def is_absence_effective_at(absence: dict, at_datetime: datetime | None = None) -> bool:
    if not absence or int(absence.get("is_active", 1) or 0) != 1:
        return False

    local_dt = _normalize_local_datetime(at_datetime)
    start_date_value = parse_iso_date(absence.get("start_date"))
    end_date_value = parse_iso_date(absence.get("end_date"))
    if not start_date_value or not end_date_value:
        return False

    start_time_value = normalize_start_time(absence.get("start_time"))
    duration_mode = (absence.get("duration_mode") or "").strip()

    if start_time_value and duration_mode != "multi_day":
        duration_hours = get_absence_duration_hours(duration_mode, absence.get("days_value"))
        if duration_hours is None:
            return start_date_value <= local_dt.date() <= end_date_value

        window_start = _local_datetime_for_date_time(start_date_value, start_time_value)
        window_end = window_start + timedelta(hours=duration_hours)
        return window_start <= local_dt < window_end

    if start_time_value and duration_mode == "multi_day":
        if not (start_date_value <= local_dt.date() <= end_date_value):
            return False
        if local_dt.date() == start_date_value:
            window_start = _local_datetime_for_date_time(start_date_value, start_time_value)
            return local_dt >= window_start
        return True

    return start_date_value <= local_dt.date() <= end_date_value


def get_absence_time_window_label(absence: dict) -> str:
    start_time_value = normalize_start_time(absence.get("start_time"))
    if not start_time_value:
        return "All day"

    duration_mode = (absence.get("duration_mode") or "").strip()
    start_date_value = parse_iso_date(absence.get("start_date"))
    if duration_mode == "multi_day" or not start_date_value:
        return f"Starts {_format_time_value(datetime.strptime(start_time_value, '%H:%M').time())}"

    duration_hours = get_absence_duration_hours(duration_mode, absence.get("days_value"))
    start_dt = _local_datetime_for_date_time(start_date_value, start_time_value)
    if duration_hours is None:
        return _format_time_value(start_dt.time())

    end_dt = start_dt + timedelta(hours=duration_hours)
    return f"{_format_time_value(start_dt.time())} - {_format_time_value(end_dt.time())}"


def _get_active_absence_for_user(user_id: int, on_date: date | None = None) -> dict | None:
    local_dt = _normalize_local_datetime()
    if on_date:
        local_dt = datetime.combine(on_date, local_dt.time(), tzinfo=get_app_zoneinfo())

    previous_day = (local_dt.date() - timedelta(days=1)).isoformat()
    next_day = (local_dt.date() + timedelta(days=1)).isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM staff_status_absences
            WHERE user_id = ?
              AND is_active = 1
              AND start_date <= ?
              AND end_date >= ?
            ORDER BY start_date DESC, id DESC
            """,
            (user_id, next_day, previous_day),
        ).fetchall()

    for row in rows:
        absence = dict(row)
        if is_absence_effective_at(absence, local_dt):
            return absence

    return None


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


def get_active_user_for_department(user_id: int, department_name: str) -> dict | None:
    department_name = normalize_department(department_name)
    if not department_name:
        return None

    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    with get_identity_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
              AND is_active = 1
              AND TRIM(COALESCE(department, '')) = ?
            """,
            (normalized_user_id, department_name),
        ).fetchone()

    if not row:
        return None

    user = dict(row)
    user["resolved_display_name"] = build_display_name(user)
    return user


def _insert_absence(
    conn,
    *,
    user_id: int,
    department_name: str,
    absence_type: str,
    start_date: str,
    end_date: str,
    duration_mode: str,
    days_value: float | None,
    start_time: str | None,
    note: str | None,
    created_by_user_id: int,
    created_by_display_name: str,
    now: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO staff_status_absences (
            user_id,
            department_name,
            absence_type,
            public_status_label,
            start_date,
            end_date,
            start_time,
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 1)
        """,
        (
            user_id,
            department_name,
            absence_type,
            DEFAULT_PUBLIC_ABSENCE_LABEL,
            start_date,
            end_date,
            start_time,
            duration_mode,
            days_value,
            normalize_text(note),
            created_by_user_id,
            created_by_display_name,
            now,
        ),
    )

    absence_id = cursor.lastrowid

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

    return absence_id


def get_absence_by_id(absence_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM staff_status_absences
            WHERE id = ?
            """,
            (absence_id,),
        ).fetchone()

    return dict(row) if row else None


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
    start_time: str | None = None,
):
    now = utc_now_iso()
    normalized = validate_absence_payload(
        user_id=user_id,
        department_name=department_name,
        absence_type=absence_type,
        start_date=start_date,
        end_date=end_date,
        duration_mode=duration_mode,
        days_value=days_value,
        start_time=start_time,
    )

    if not get_active_user_for_department(
        normalized["user_id"],
        normalized["department_name"],
    ):
        raise StaffStatusValidationError("Selected staff member does not belong to this department.")

    with get_connection() as conn:
        absence_id = _insert_absence(
            conn,
            user_id=normalized["user_id"],
            department_name=normalized["department_name"],
            absence_type=normalized["absence_type"],
            start_date=normalized["start_date"],
            end_date=normalized["end_date"],
            duration_mode=normalized["duration_mode"],
            days_value=normalized["days_value"],
            start_time=normalized["start_time"],
            note=note,
            created_by_user_id=created_by_user_id,
            created_by_display_name=created_by_display_name,
            now=now,
        )
        conn.commit()
    return get_absence_by_id(absence_id)
        
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
    department_name: str | None = None,
    start_time: str | None = None,
):
    now = utc_now_iso()

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM staff_status_absences
            WHERE id = ?
            """,
            (absence_id,),
        ).fetchone()

        if not existing:
            raise StaffStatusValidationError("Absence not found.")

        existing = dict(existing)
        target_department = normalize_department(department_name) or existing["department_name"]
        if existing["department_name"] != target_department:
            raise StaffStatusValidationError("Absence does not belong to this department.")

        normalized = validate_absence_payload(
            user_id=existing["user_id"],
            department_name=target_department,
            absence_type=absence_type,
            start_date=start_date,
            end_date=end_date,
            duration_mode=duration_mode,
            days_value=days_value,
            start_time=start_time,
        )

        result = conn.execute(
            """
            UPDATE staff_status_absences
            SET
                absence_type = ?,
                start_date = ?,
                end_date = ?,
                start_time = ?,
                duration_mode = ?,
                days_value = ?,
                note = ?,
                updated_by_user_id = ?,
                updated_by_display_name = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                normalized["absence_type"],
                normalized["start_date"],
                normalized["end_date"],
                normalized["start_time"],
                normalized["duration_mode"],
                normalized["days_value"],
                normalize_text(note),
                updated_by_user_id,
                updated_by_display_name,
                now,
                absence_id,
            ),
        )
        if result.rowcount == 0:
            raise StaffStatusValidationError("Absence could not be updated.")
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
        row["duration_label"] = get_absence_duration_label(row.get("duration_mode"))
        row["hours_value"] = absence_days_to_hours(row.get("days_value"))
        row["start_time_label"] = format_start_time(row.get("start_time"))
        row["time_window_label"] = get_absence_time_window_label(row)

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
    return labels.get(duration_mode or "", (duration_mode or "").replace("_", " ").title() or "N/A")


def absence_days_to_hours(days_value) -> str:
    if days_value is None:
        return "N/A"

    try:
        hours = float(days_value) * 8
    except (TypeError, ValueError):
        return "N/A"

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


def normalize_absence_table_sort(
    sort_key: str | None,
    sort_direction: str | None,
) -> tuple[str | None, str]:
    cleaned_key = (sort_key or "").strip().lower()
    if cleaned_key not in ABSENCE_TABLE_SORT_KEYS:
        cleaned_key = None

    cleaned_direction = (sort_direction or "").strip().lower()
    if cleaned_direction not in {"asc", "desc"}:
        cleaned_direction = "asc"

    return cleaned_key, cleaned_direction


def _absence_sort_number(value) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _absence_sort_value(row: dict, sort_key: str):
    if sort_key == "user":
        return (row.get("user_display_name") or "").lower()
    if sort_key == "type":
        return (row.get("absence_type") or "").lower()
    if sort_key == "start":
        return row.get("start_date") or ""
    if sort_key == "end":
        return row.get("end_date") or ""
    if sort_key == "time":
        return row.get("start_time") or ""
    if sort_key in {"duration", "days", "hours"}:
        return _absence_sort_number(row.get("days_value"))
    if sort_key == "entered_by":
        return (row.get("created_by_display_name") or "").lower()
    if sort_key == "created":
        return row.get("created_at") or ""
    return None


def _sort_absence_rows(
    rows: list[dict],
    *,
    sort_key: str | None,
    sort_direction: str,
) -> list[dict]:
    if not sort_key:
        return rows

    reverse = sort_direction == "desc"

    def has_value(row: dict) -> bool:
        value = _absence_sort_value(row, sort_key)
        return value not in (None, "")

    populated_rows = [row for row in rows if has_value(row)]
    empty_rows = [row for row in rows if not has_value(row)]

    populated_rows.sort(
        key=lambda row: (
            _absence_sort_value(row, sort_key),
            row.get("start_date") or "",
            row.get("end_date") or "",
            int(row.get("id") or 0),
        ),
        reverse=reverse,
    )

    return populated_rows + empty_rows


def list_absences_for_department(
    *,
    department_name: str,
    timing: str = "upcoming",
    absence_types: list[str] | None = None,
    user_ids: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    sort_key: str | None = None,
    sort_direction: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    department_name = normalize_department(department_name)
    if not department_name:
        return []

    normalized_sort_key, normalized_sort_direction = normalize_absence_table_sort(
        sort_key,
        sort_direction,
    )

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

    if limit and not normalized_sort_key:
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
        row["start_time_label"] = format_start_time(row.get("start_time"))
        row["time_window_label"] = get_absence_time_window_label(row)

    rows = _sort_absence_rows(
        rows,
        sort_key=normalized_sort_key,
        sort_direction=normalized_sort_direction,
    )

    if limit and normalized_sort_key:
        rows = rows[: int(limit)]

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
        "Start Time",
        "Time Window",
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
            item.get("start_time_label") or "",
            item.get("time_window_label") or "",
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
    selected_user_ids = set()
    for item in user_ids or []:
        try:
            selected_user_ids.add(int(item))
        except (TypeError, ValueError):
            continue

    users = sorted(
        [
            user
            for user in list_active_users_for_department(department_name)
            if not selected_user_ids or int(user["id"]) in selected_user_ids
        ],
        key=lambda item: (
            (item.get("last_name") or item.get("resolved_display_name") or "").lower(),
            (item.get("first_name") or "").lower(),
            (item.get("resolved_display_name") or "").lower(),
        ),
    )

    rows = list_absences_for_department(
        department_name=department_name,
        timing="all",
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

    rows_by_user: dict[int, list[dict]] = {}
    for row in rows:
        try:
            row_user_id = int(row["user_id"])
        except (TypeError, ValueError):
            continue
        rows_by_user.setdefault(row_user_id, []).append(row)

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    story = []

    if start_date or end_date:
        period_label = f"{start_date or 'Any'} to {end_date or 'Any'}"
    else:
        period_label = "Any Date"

    if absence_types:
        absence_type_label = ", ".join([item.title() for item in absence_types])
    else:
        absence_type_label = "All"

    for index, user in enumerate(users):
        user_rows = rows_by_user.get(int(user["id"]), [])
        total_days = sum(float(row.get("days_value") or 0) for row in user_rows)
        total_hours = total_days * 8

        story.append(Paragraph(user["resolved_display_name"], styles["Title"]))
        story.append(Paragraph(f"Department: {department_name}", styles["Normal"]))
        story.append(Paragraph(f"Reporting Period: {period_label}", styles["Normal"]))
        story.append(Paragraph(f"Absence Types: {absence_type_label}", styles["Normal"]))
        story.append(Spacer(1, 10))

        if user_rows:
            summary_text = (
                f"Total: {len(user_rows)} absence record"
                f"{'' if len(user_rows) == 1 else 's'}; "
                f"{total_days:g} day{'' if total_days == 1 else 's'}; "
                f"{total_hours:g} hour{'' if total_hours == 1 else 's'}"
            )
            story.append(Paragraph(summary_text, styles["Heading3"]))
            story.append(Spacer(1, 8))

            data = [[
                "Date",
                "Type",
                "Duration",
                "Time",
                "Days",
                "Hours",
                "Note",
            ]]

            for item in user_rows:
                date_label = item.get("start_date") or ""
                if item.get("end_date") and item.get("end_date") != item.get("start_date"):
                    date_label = f"{item.get('start_date') or ''} to {item.get('end_date') or ''}"

                data.append([
                    date_label,
                    (item.get("absence_type") or "").title(),
                    item.get("duration_label") or "",
                    item.get("time_window_label") or "All day",
                    str(item.get("days_value") if item.get("days_value") is not None else ""),
                    item.get("hours_value") or "",
                    item.get("note") or "",
                ])

            table = Table(
                data,
                repeatRows=1,
                colWidths=[88, 68, 116, 96, 42, 44, 150],
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
        else:
            story.append(Paragraph("No absences", styles["Heading2"]))

        if index < len(users) - 1:
            story.append(PageBreak())

    if not users:
        story.append(Paragraph(f"{department_name} Absence Report", styles["Title"]))
        story.append(Paragraph("No active staff members found for this department.", styles["Normal"]))

    doc.build(story)

    safe_department = department_name.lower().replace(" ", "-")
    if start_date and end_date:
        filename = f"{safe_department}-absences-{start_date}-to-{end_date}.pdf"
    else:
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


ABSENCE_REPORT_DATE_RANGE_OPTIONS = [
    {"key": "this_month", "label": "This Month"},
    {"key": "last_month", "label": "Previous Month"},
    {"key": "year_to_date", "label": "Year to Date"},
    {"key": "current_school_year", "label": "Current School Year"},
    {"key": "custom", "label": "Custom Range"},
]


def get_absence_report_date_range_options() -> list[dict]:
    return list(ABSENCE_REPORT_DATE_RANGE_OPTIONS)


def resolve_absence_report_date_range(
    *,
    range_key: str | None,
    custom_start_date: str | None = None,
    custom_end_date: str | None = None,
    today: date | None = None,
) -> dict:
    today = today or get_local_now().date()
    key = (range_key or "this_month").strip().lower()
    valid_keys = {item["key"] for item in ABSENCE_REPORT_DATE_RANGE_OPTIONS}
    if key not in valid_keys:
        key = "this_month"

    if key == "this_month":
        start = today.replace(day=1)
        end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        label = "This Month"
    elif key == "last_month":
        first_this_month = today.replace(day=1)
        end = first_this_month - timedelta(days=1)
        start = end.replace(day=1)
        label = "Previous Month"
    elif key == "year_to_date":
        start = today.replace(month=1, day=1)
        end = today
        label = "Year to Date"
    elif key == "current_school_year":
        school_year = get_current_school_year_range(today)
        start = school_year["start_date"]
        end = school_year["end_date"]
        label = f"Current School Year ({school_year['label']})"
    else:
        start = parse_iso_date(custom_start_date)
        end = parse_iso_date(custom_end_date)
        if not start or not end:
            raise StaffStatusValidationError("Custom range requires a valid start and end date.")
        if end < start:
            raise StaffStatusValidationError("Custom range end date cannot be before the start date.")
        label = "Custom Range"

    return {
        "key": key,
        "label": label,
        "start_date": start,
        "end_date": end,
        "start_date_iso": start.isoformat(),
        "end_date_iso": end.isoformat(),
    }


def update_absence_form_integration_settings(
    *,
    approval_manager_email: str | None,
    notification_sender_email: str | None,
) -> None:
    manager_email = (approval_manager_email or DEFAULT_ABSENCE_APPROVAL_MANAGER_EMAIL).strip().lower()
    sender_email = (notification_sender_email or "").strip().lower()

    set_setting(f"{ABSENCE_FORM_SETTING_PREFIX}.approval_manager_email", manager_email)
    set_setting(f"{ABSENCE_NOTIFICATION_SETTING_PREFIX}.sender_email", sender_email)


def get_absence_form_integration_settings() -> dict:
    sender_email = (
        get_setting(f"{ABSENCE_NOTIFICATION_SETTING_PREFIX}.sender_email", "")
        or get_setting("mail.smtp_username", "")
        or ""
    )

    return {
        "approval_manager_email": (
            get_setting(
                f"{ABSENCE_FORM_SETTING_PREFIX}.approval_manager_email",
                DEFAULT_ABSENCE_APPROVAL_MANAGER_EMAIL,
            )
            or DEFAULT_ABSENCE_APPROVAL_MANAGER_EMAIL
        ),
        "notification_sender_email": sender_email,
    }


def _pending_absence_request_from_row(row) -> dict | None:
    if row is None:
        return None

    item = dict(row)
    item["duration_label"] = get_absence_duration_label(item.get("duration_mode"))
    item["hours_value"] = absence_days_to_hours(item.get("days_value"))
    item["start_time_label"] = format_start_time(item.get("start_time"))
    item["time_window_label"] = get_absence_time_window_label(item)
    item["date_range_label"] = format_friendly_date_range(item.get("start_date"), item.get("end_date"))
    item["submitted_at_label"] = format_friendly_timestamp(item.get("submitted_at"))
    item["reviewed_at_label"] = format_friendly_timestamp(item.get("reviewed_at"))
    item["status_label"] = "Denied" if item.get("status") == "rejected" else str(item.get("status") or "").title()
    return item


def get_pending_absence_request_by_id(request_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM staff_status_pending_absence_requests
            WHERE id = ?
            """,
            (request_id,),
        ).fetchone()

    return _pending_absence_request_from_row(row)


def get_pending_absence_request_by_submission_uuid(submission_uuid: str) -> dict | None:
    submission_uuid = normalize_text(submission_uuid)
    if not submission_uuid:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM staff_status_pending_absence_requests
            WHERE submission_uuid = ?
            """,
            (submission_uuid,),
        ).fetchone()

    return _pending_absence_request_from_row(row)


def list_pending_absence_requests(status: str | None = "pending") -> list[dict]:
    normalized_status = (status or "").strip().lower()
    params = []
    where_sql = ""

    if normalized_status in VALID_PENDING_ABSENCE_STATUSES:
        where_sql = "WHERE status = ?"
        params.append(normalized_status)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM staff_status_pending_absence_requests
            {where_sql}
            ORDER BY submitted_at DESC, id DESC
            """,
            params,
        ).fetchall()

    return [_pending_absence_request_from_row(row) for row in rows]


def list_absence_requests_for_department(
    department_name: str,
    status: str | None = None,
) -> list[dict]:
    normalized_status = (status or "").strip().lower()
    if normalized_status == "denied":
        normalized_status = "rejected"
    params = [department_name.strip()]
    status_sql = ""
    if normalized_status in VALID_PENDING_ABSENCE_STATUSES:
        status_sql = "AND status = ?"
        params.append(normalized_status)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM staff_status_pending_absence_requests
            WHERE department_name = ?
            {status_sql}
            ORDER BY submitted_at DESC, id DESC
            """,
            params,
        ).fetchall()
    return [_pending_absence_request_from_row(row) for row in rows]


def _validate_submission_uuid(value: str | None) -> str:
    submission_uuid = normalize_text(value)
    if not submission_uuid or len(submission_uuid) > 120:
        raise StaffStatusValidationError("A valid submission id is required.")
    return submission_uuid


def _is_department_enabled(department_name: str) -> bool:
    department = get_department_record(department_name)
    if not department:
        department = ensure_department_record(department_name)
    return int(department.get("is_enabled", 0) or 0) == 1


def create_pending_absence_request_from_public_submission(
    *,
    payload: dict,
    source_ip: str | None = None,
    source_user_agent: str | None = None,
) -> tuple[dict, bool]:
    submission_uuid = _validate_submission_uuid(
        payload.get("submission_uuid") or payload.get("idempotency_key")
    )

    existing = get_pending_absence_request_by_submission_uuid(submission_uuid)
    if existing:
        return existing, False

    staff_email = (payload.get("staff_email") or payload.get("email") or "").strip().lower()
    if not staff_email or "@" not in staff_email:
        raise StaffStatusValidationError("A valid district email is required.")

    user = get_user_by_email(staff_email)
    if not user or int(user.get("is_active") or 0) != 1:
        raise StaffStatusValidationError("Staff member could not be found.")

    department_name = normalize_department(user.get("department"))
    if not department_name:
        raise StaffStatusValidationError("Staff member does not have a department.")

    if not _is_department_enabled(department_name):
        raise StaffStatusValidationError("Staff Status is not available for this department.")

    note = normalize_text(payload.get("note"))
    if note and len(note) > 1000:
        raise StaffStatusValidationError("Notes cannot exceed 1000 characters.")

    duration_mode = (payload.get("duration_mode") or "").strip()
    days_value = payload.get("days_value")
    if duration_mode != "multi_day":
        days_value = ABSENCE_DURATION_LOOKUP.get(duration_mode)

    normalized = validate_absence_payload(
        user_id=user["id"],
        department_name=department_name,
        absence_type=payload.get("absence_type") or "",
        start_date=payload.get("start_date") or "",
        end_date=payload.get("end_date") or payload.get("start_date") or "",
        duration_mode=duration_mode,
        days_value=days_value,
        start_time=payload.get("start_time") or "",
    )

    settings = get_absence_form_integration_settings()
    now = utc_now_iso()

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO staff_status_pending_absence_requests (
                    submission_uuid,
                    user_id,
                    staff_email,
                    staff_display_name,
                    department_name,
                    absence_type,
                    public_status_label,
                    start_date,
                    end_date,
                    start_time,
                    duration_mode,
                    days_value,
                    note,
                    status,
                    approval_manager_email,
                    submitted_at,
                    source_ip,
                    source_user_agent,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_uuid,
                    normalized["user_id"],
                    staff_email,
                    build_display_name(user),
                    normalized["department_name"],
                    normalized["absence_type"],
                    DEFAULT_PUBLIC_ABSENCE_LABEL,
                    normalized["start_date"],
                    normalized["end_date"],
                    normalized["start_time"],
                    normalized["duration_mode"],
                    normalized["days_value"],
                    note,
                    settings["approval_manager_email"],
                    now,
                    source_ip,
                    source_user_agent[:255] if source_user_agent else None,
                    now,
                    now,
                ),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        existing = get_pending_absence_request_by_submission_uuid(submission_uuid)
        if existing:
            return existing, False
        raise

    return get_pending_absence_request_by_id(cursor.lastrowid), True


def approve_pending_absence_request(
    *,
    request_id: int,
    reviewed_by_user_id: int | None,
    reviewed_by_display_name: str,
    reviewed_by_email: str | None = None,
    reviewed_at: str | None = None,
    review_source: str = "launchpad",
    decision_note: str | None = None,
) -> dict:
    now = reviewed_at or utc_now_iso()
    normalized_note = normalize_text(decision_note)
    if normalized_note and len(normalized_note) > 1000:
        raise StaffStatusValidationError("Decision note cannot exceed 1000 characters.")

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT *
            FROM staff_status_pending_absence_requests
            WHERE id = ?
            """,
            (request_id,),
        ).fetchone()

        if not row:
            conn.rollback()
            raise StaffStatusValidationError("Absence request not found.")

        request_record = dict(row)
        if request_record.get("status") != "pending":
            conn.rollback()
            raise PendingAbsenceRequestStateError("This absence request has already been reviewed.")

        if not get_active_user_for_department(
            request_record["user_id"],
            request_record["department_name"],
        ):
            conn.rollback()
            raise StaffStatusValidationError("Staff member no longer belongs to this department.")

        department_row = conn.execute(
            """
            SELECT is_enabled
            FROM staff_status_departments
            WHERE department_name = ?
            """,
            (request_record["department_name"],),
        ).fetchone()

        if not department_row or int(department_row["is_enabled"] or 0) != 1:
            conn.rollback()
            raise StaffStatusValidationError("Staff Status is not available for this department.")

        absence_id = _insert_absence(
            conn,
            user_id=request_record["user_id"],
            department_name=request_record["department_name"],
            absence_type=request_record["absence_type"],
            start_date=request_record["start_date"],
            end_date=request_record["end_date"],
            duration_mode=request_record["duration_mode"],
            days_value=request_record["days_value"],
            start_time=request_record["start_time"],
            note=request_record.get("note"),
            created_by_user_id=reviewed_by_user_id or 0,
            created_by_display_name=reviewed_by_display_name,
            now=now,
        )

        conn.execute(
            """
            UPDATE staff_status_pending_absence_requests
            SET status = 'approved',
                reviewed_at = ?,
                reviewed_by_user_id = ?,
                reviewed_by_display_name = ?,
                reviewed_by_email = ?,
                review_source = ?,
                decision_note = ?,
                created_absence_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                reviewed_by_user_id,
                reviewed_by_display_name,
                normalize_text(reviewed_by_email),
                normalize_text(review_source),
                normalized_note,
                absence_id,
                now,
                request_id,
            ),
        )
        conn.commit()

    return get_pending_absence_request_by_id(request_id)


def reject_pending_absence_request(
    *,
    request_id: int,
    reviewed_by_user_id: int | None,
    reviewed_by_display_name: str,
    reviewed_by_email: str | None = None,
    reviewed_at: str | None = None,
    review_source: str = "launchpad",
    decision_note: str | None = None,
) -> dict:
    now = reviewed_at or utc_now_iso()
    normalized_note = normalize_text(decision_note)
    if normalized_note and len(normalized_note) > 1000:
        raise StaffStatusValidationError("Decision note cannot exceed 1000 characters.")

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT *
            FROM staff_status_pending_absence_requests
            WHERE id = ?
            """,
            (request_id,),
        ).fetchone()

        if not row:
            conn.rollback()
            raise StaffStatusValidationError("Absence request not found.")

        request_record = dict(row)
        if request_record.get("status") != "pending":
            conn.rollback()
            raise PendingAbsenceRequestStateError("This absence request has already been reviewed.")

        conn.execute(
            """
            UPDATE staff_status_pending_absence_requests
            SET status = 'rejected',
                reviewed_at = ?,
                reviewed_by_user_id = ?,
                reviewed_by_display_name = ?,
                reviewed_by_email = ?,
                review_source = ?,
                decision_note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                reviewed_by_user_id,
                reviewed_by_display_name,
                normalize_text(reviewed_by_email),
                normalize_text(review_source),
                normalized_note,
                now,
                request_id,
            ),
        )
        conn.commit()

    return get_pending_absence_request_by_id(request_id)


def _update_pending_request_fields(request_id: int, fields: dict) -> None:
    allowed = {
        "review_notification_sent_at",
        "review_notification_error",
        "result_notification_status",
        "result_notification_attempted_at",
        "result_notification_sent_at",
        "result_notification_error",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE staff_status_pending_absence_requests SET {assignments}, updated_at = ? WHERE id = ?",
            [*updates.values(), utc_now_iso(), request_id],
        )
        conn.commit()


def _email_summary_html(request_record: dict) -> str:
    absence_type = escape(str(request_record.get("absence_type") or "").title())
    date_range = escape(format_friendly_date_range(request_record.get("start_date"), request_record.get("end_date")))
    duration = escape(str(request_record.get("duration_label") or get_absence_duration_label(request_record.get("duration_mode"))))
    hours = escape(str(request_record.get("hours_value") or absence_days_to_hours(request_record.get("days_value"))))
    time_label = escape(str(request_record.get("time_window_label") or get_absence_time_window_label(request_record)))
    return f"""
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;background:#f8fafc;border:1px solid #dbe4ee;border-radius:12px;">
        <tr><td style="padding:20px;">
          <div style="font-size:13px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#2563eb;margin-bottom:8px;">{absence_type}</div>
          <div style="font-size:20px;font-weight:800;color:#172033;line-height:1.35;margin-bottom:8px;">{date_range}</div>
          <div style="font-size:15px;color:#475569;line-height:1.6;">{duration} &middot; {hours} hours<br>{time_label}</div>
        </td></tr>
      </table>
    """


def _email_shell(*, eyebrow: str, title: str, intro_html: str, body_html: str, footer_html: str) -> str:
    return f"""
    <html><body style="margin:0;padding:0;background:#eef3f8;font-family:Arial,Helvetica,sans-serif;color:#172033;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;background:#eef3f8;">
        <tr><td align="center" style="padding:24px 12px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;border-collapse:separate;background:#ffffff;border:1px solid #dbe4ee;border-radius:16px;overflow:hidden;">
            <tr><td style="padding:24px 26px;background:#172b4d;color:#ffffff;">
              <div style="font-size:20px;font-weight:800;">Launchpad</div><div style="font-size:13px;color:#cbd5e1;margin-top:3px;">Staff Status</div>
            </td></tr>
            <tr><td style="padding:28px 26px;">
              <div style="font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:#2563eb;margin-bottom:9px;">{escape(eyebrow)}</div>
              <h1 style="margin:0 0 12px;font-size:27px;line-height:1.25;color:#172033;">{escape(title)}</h1>
              <div style="font-size:16px;line-height:1.55;color:#475569;margin-bottom:22px;">{intro_html}</div>
              {body_html}
              <div style="margin-top:22px;font-size:13px;line-height:1.5;color:#64748b;">{footer_html}</div>
            </td></tr>
            <tr><td style="padding:18px 26px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b;">Sheridan School District &middot; Launchpad</td></tr>
          </table>
        </td></tr>
      </table>
    </body></html>
    """


def send_pending_absence_request_email(request_record: dict) -> bool:
    if request_record.get("review_notification_sent_at"):
        return False
    settings = get_absence_form_integration_settings()
    sender_email = (settings.get("notification_sender_email") or "").strip()
    recipient_email = (request_record.get("approval_manager_email") or "").strip()

    if not sender_email:
        raise ValueError("Staff Status notification sender email is not configured.")

    review_base_url = (get_setting("staff_status.absence_google_sync.review_web_app_url", "") or "").strip()
    if not review_base_url:
        raise ValueError("The authenticated absence review web app URL is not configured.")
    separator = "&" if "?" in review_base_url else "?"
    review_url = f"{review_base_url}{separator}action=review&id={quote(str(request_record['submission_uuid']))}"

    subject = f"New Absence Request — {request_record.get('staff_display_name')}"
    html_staff_display_name = escape(str(request_record.get("staff_display_name") or ""))
    html_department_name = escape(str(request_record.get("department_name") or ""))
    html_note = escape(str(request_record.get("note") or "No note provided."))
    html_submitted_at = escape(format_friendly_timestamp(request_record.get("submitted_at")))
    html_review_url = escape(review_url, quote=True)

    text_body = "\n".join([
        "A new Staff Status absence request is waiting for review.",
        "",
        f"Staff Member: {request_record.get('staff_display_name')}",
        f"Department: {request_record.get('department_name')}",
        f"Date: {format_friendly_date_range(request_record.get('start_date'), request_record.get('end_date'))}",
        f"Absence Type: {(request_record.get('absence_type') or '').title()}",
        f"Duration: {request_record.get('duration_label')}",
        f"Time: {request_record.get('time_window_label')}",
        f"Notes: {request_record.get('note') or 'None'}",
        f"Submitted: {format_friendly_timestamp(request_record.get('submitted_at'))}",
        "",
        f"Review Absence Request: {review_url}",
    ])

    html_body = _email_shell(
        eyebrow="New Absence Request",
        title=html_staff_display_name,
        intro_html=f"<strong style='color:#172033'>{html_department_name}</strong><br>A request is ready for your review.",
        body_html=f"""
          {_email_summary_html(request_record)}
          <div style="margin-top:20px;"><div style="font-size:13px;font-weight:800;color:#172033;margin-bottom:6px;">Staff Note</div><div style="font-size:15px;line-height:1.55;color:#475569;white-space:pre-wrap;">{html_note}</div></div>
          <table role="presentation" cellspacing="0" cellpadding="0" style="margin-top:24px;"><tr><td style="border-radius:10px;background:#2563eb;"><a href="{html_review_url}" style="display:inline-block;padding:14px 20px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:800;">Review Absence Request</a></td></tr></table>
        """,
        footer_html=f"Submitted {html_submitted_at}",
    )

    try:
        send_mail(sender_email=sender_email, recipient_email=recipient_email, subject=subject, text_body=text_body, html_body=html_body)
    except Exception as exc:
        _update_pending_request_fields(request_record["id"], {"review_notification_error": str(exc)[:500]})
        raise
    sent_at = utc_now_iso()
    _update_pending_request_fields(request_record["id"], {"review_notification_sent_at": sent_at, "review_notification_error": None})
    return True


def send_absence_decision_result_email_once(request_record: dict) -> bool:
    attempted_at = utc_now_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM staff_status_pending_absence_requests WHERE id = ?",
            (request_record["id"],),
        ).fetchone()
        if not row:
            conn.rollback()
            return False
        claim = dict(row)
        previous_attempt = None
        if claim.get("result_notification_attempted_at"):
            try:
                previous_attempt = datetime.fromisoformat(
                    claim["result_notification_attempted_at"].replace("Z", "+00:00"))
                if previous_attempt.tzinfo is None:
                    previous_attempt = previous_attempt.replace(tzinfo=timezone.utc)
            except ValueError:
                previous_attempt = None
        sending_is_fresh = (
            claim.get("result_notification_status") == "sending"
            and previous_attempt
            and previous_attempt > datetime.now(timezone.utc) - timedelta(minutes=15)
        )
        if (claim.get("status") not in {"approved", "rejected"}
                or claim.get("result_notification_sent_at") or sending_is_fresh):
            conn.rollback()
            return False
        conn.execute(
            """
            UPDATE staff_status_pending_absence_requests
            SET result_notification_status = 'sending',
                result_notification_attempted_at = ?,
                result_notification_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (attempted_at, attempted_at, request_record["id"]),
        )
        conn.commit()
    latest = get_pending_absence_request_by_id(request_record["id"])
    settings = get_absence_form_integration_settings()
    sender_email = (settings.get("notification_sender_email") or "").strip()
    approved = latest["status"] == "approved"
    status_label = "Approved" if approved else "Denied"
    start = parse_iso_date(latest.get("start_date"))
    subject_date = start.strftime("%B %d").replace(" 0", " ") if start else "Absence Request"
    reviewer = latest.get("reviewed_by_display_name") or latest.get("reviewed_by_email") or "Your reviewer"
    decision_note = latest.get("decision_note") or ""
    outcome = "Your absence has been added to Staff Status." if approved else "No Staff Status absence was created."
    text_lines = [
        f"Your absence request was {status_label.lower()}.", "",
        format_friendly_date_range(latest.get("start_date"), latest.get("end_date")),
        str(latest.get("absence_type") or "").title(),
        str(latest.get("duration_label") or ""), "",
        f"Reviewed by {reviewer}",
        format_friendly_timestamp(latest.get("reviewed_at")),
    ]
    if decision_note:
        text_lines.extend(["", "Manager Note", decision_note])
    text_lines.extend(["", outcome])
    note_html = ""
    if decision_note:
        note_html = f"<div style='margin-top:20px;'><div style='font-size:13px;font-weight:800;margin-bottom:6px;'>Manager Note</div><div style='white-space:pre-wrap;color:#475569;'>{escape(decision_note)}</div></div>"
    html_body = _email_shell(
        eyebrow=status_label,
        title=f"Your Absence Request Was {status_label}",
        intro_html=escape(outcome),
        body_html=f"{_email_summary_html(latest)}{note_html}",
        footer_html=f"Reviewed by {escape(str(reviewer))}<br>{escape(format_friendly_timestamp(latest.get('reviewed_at')))}",
    )
    try:
        send_mail(
            sender_email=sender_email,
            recipient_email=latest["staff_email"],
            subject=f"Absence Request {status_label} — {subject_date}",
            text_body="\n".join(text_lines),
            html_body=html_body,
        )
    except Exception as exc:
        _update_pending_request_fields(latest["id"], {
            "result_notification_status": "error",
            "result_notification_error": str(exc)[:500],
        })
        raise
    sent_at = utc_now_iso()
    _update_pending_request_fields(latest["id"], {
        "result_notification_status": "sent",
        "result_notification_sent_at": sent_at,
        "result_notification_error": None,
    })
    return True


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
