from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import current_app


def utc_now():
    return datetime.now(timezone.utc)


def utc_now_iso():
    return utc_now().isoformat()


def to_system_timezone(dt):
    if dt is None:
        return None

    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    tz_name = current_app.config.get("SYSTEM_TIMEZONE", "UTC")

    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc

    return dt.astimezone(tz)


def format_system_time(dt, fmt="%m/%d/%Y %I:%M %p"):
    dt = to_system_timezone(dt)
    if not dt:
        return None
    return dt.strftime(fmt)