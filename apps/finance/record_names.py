"""Keep imported titles intact while displaying user-maintained names."""


def record_display_name(record):
    if not record:
        return ""
    record = dict(record)
    return (record.get("friendly_name") or "").strip() or record.get("title") or ""
