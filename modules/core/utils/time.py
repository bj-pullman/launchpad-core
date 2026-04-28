from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app

from modules.core.settings.settings_service import get_setting


def utc_now():
    return datetime.now(timezone.utc)


def utc_now_iso():
    return utc_now().isoformat()


def format_system_time(value, include_seconds=False):
    if not value:
        return ""

    raw = str(value).strip()
    if not raw:
        return ""

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    timezone_name = get_setting(
        "general.timezone",
        current_app.config.get("SYSTEM_TIMEZONE", "UTC"),
    ) or "UTC"

    try:
        target_tz = ZoneInfo(timezone_name)
    except Exception:
        target_tz = timezone.utc

    local_dt = dt.astimezone(target_tz)

    time_format = get_setting("general.time_format", "12h") or "12h"
    date_format = get_setting("general.date_format", "mdy") or "mdy"

    if date_format == "ymd":
        date_part = local_dt.strftime("%Y-%m-%d")
    elif date_format == "dmy":
        date_part = local_dt.strftime("%d/%m/%Y")
    else:
        date_part = local_dt.strftime("%m/%d/%Y")

    if time_format == "24h":
        time_part = local_dt.strftime("%H:%M:%S" if include_seconds else "%H:%M")
    else:
        hour = local_dt.strftime("%I").lstrip("0") or "12"
        time_part = f"{hour}:{local_dt.strftime('%M:%S' if include_seconds else '%M')} {local_dt.strftime('%p')}"

    return f"{date_part} {time_part}"