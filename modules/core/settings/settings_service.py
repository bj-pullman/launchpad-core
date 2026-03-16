from datetime import datetime, timezone

from modules.core.settings.settings_db import get_connection


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def get_setting(setting_key: str, default=None):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM app_settings
            WHERE setting_key = ?
            """,
            (setting_key,),
        ).fetchone()

    if not row:
        return default

    return row["setting_value"]


def get_setting_record(setting_key: str):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM app_settings
            WHERE setting_key = ?
            """,
            (setting_key,),
        ).fetchone()

    return row_to_dict(row)


def set_setting(setting_key: str, setting_value, is_sensitive: int = 0):
    now = utc_now_iso()
    existing = get_setting_record(setting_key)

    with get_connection() as conn:
        if existing:
            conn.execute(
                """
                UPDATE app_settings
                SET setting_value = ?, is_sensitive = ?, updated_at = ?
                WHERE setting_key = ?
                """,
                (setting_value, int(is_sensitive), now, setting_key),
            )
        else:
            conn.execute(
                """
                INSERT INTO app_settings (
                    setting_key,
                    setting_value,
                    is_sensitive,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (setting_key, setting_value, int(is_sensitive), now, now),
            )
        conn.commit()


def get_bool_setting(setting_key: str, default: bool = False) -> bool:
    value = get_setting(setting_key, None)
    if value is None:
        return default

    return str(value).strip().lower() in ("1", "true", "yes", "on")