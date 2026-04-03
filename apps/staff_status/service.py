import json, zoneinfo, secrets
from datetime import date, datetime, timezone
from flask import current_app, url_for

from .db import get_connection
from modules.core.identity.identity_db import get_connection as get_identity_connection
from modules.core.settings.settings_service import get_setting

from tasks.events import publish_department_update

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
                        absence["updated_at"] or absence["created_at"]
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
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")

    if base:
        return f"{base}{path}"

    return url_for(endpoint, _external=True, **values)