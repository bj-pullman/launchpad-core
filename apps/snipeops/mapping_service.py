from datetime import datetime, timezone

from apps.snipeops.mapping_db import get_connection


VALID_SOURCES = {"any", "intune", "mosyle"}
VALID_FIELDS = {"model", "manufacturer", "os_version", "device_type"}


DEFAULT_OS_VERSION_MAPPINGS = [
    ("any", "os_version", "10.0.19045", "Windows 10 22H2"),
    ("any", "os_version", "10.0.22000", "Windows 11 21H2"),
    ("any", "os_version", "10.0.22621", "Windows 11 22H2"),
    ("any", "os_version", "10.0.22631", "Windows 11 23H2"),
    ("any", "os_version", "10.0.26100", "Windows 11 24H2"),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_source(value: str | None) -> str:
    value = (value or "any").strip().lower()
    if value not in VALID_SOURCES:
        return "any"
    return value


def normalize_field(value: str | None) -> str:
    value = (value or "").strip().lower()
    if value not in VALID_FIELDS:
        raise ValueError("Invalid mapping field.")
    return value


def normalize_raw_value(value: str | None) -> str:
    return (value or "").strip()


def normalize_mapped_value(value: str | None) -> str:
    return (value or "").strip()


def normalize_manufacturer_fallback(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    abbreviated = {"hp", "ibm", "lg", "msi", "nec"}

    if raw.lower() in abbreviated:
        return raw.upper()

    cleaned = raw.replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() for part in cleaned.split())


def normalize_default(field: str, value: str | None) -> str:
    raw = (value or "").strip()

    if not raw:
        return ""

    if field == "manufacturer":
        return normalize_manufacturer_fallback(raw)

    return raw


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def list_mappings(field: str | None = None, source: str | None = None) -> list[dict]:
    sql = """
        SELECT *
        FROM snipeops_mappings
    """
    params = []
    where = []

    if field:
        where.append("field = ?")
        params.append(normalize_field(field))

    if source:
        where.append("source = ?")
        params.append(normalize_source(source))

    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += """
        ORDER BY
            field COLLATE NOCASE,
            source COLLATE NOCASE,
            raw_value COLLATE NOCASE
    """

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]


def get_mapping_by_id(mapping_id: int):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM snipeops_mappings
            WHERE id = ?
            """,
            (mapping_id,),
        ).fetchone()

    return row_to_dict(row)


def find_mapping(source: str, field: str, raw_value: str):
    source = normalize_source(source)
    field = normalize_field(field)
    raw_value = normalize_raw_value(raw_value)

    if not raw_value:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM snipeops_mappings
            WHERE source = ? AND field = ? AND raw_value = ?
            """,
            (source, field, raw_value),
        ).fetchone()

        if row:
            return row_to_dict(row)

        if source != "any":
            row = conn.execute(
                """
                SELECT *
                FROM snipeops_mappings
                WHERE source = 'any' AND field = ? AND raw_value = ?
                """,
                (field, raw_value),
            ).fetchone()

    return row_to_dict(row)


def apply_mapping(source: str, field: str, raw_value: str):
    field = normalize_field(field)
    raw_value = normalize_raw_value(raw_value)

    mapping = find_mapping(source, field, raw_value)
    if mapping:
        return {
            "value": mapping["mapped_value"],
            "mapped": True,
            "mapping": mapping,
        }

    return {
        "value": normalize_default(field, raw_value),
        "mapped": False,
        "mapping": None,
    }


def upsert_mapping(
    source: str,
    field: str,
    raw_value: str,
    mapped_value: str,
    notes: str | None = None,
):
    source = normalize_source(source)
    field = normalize_field(field)
    raw_value = normalize_raw_value(raw_value)
    mapped_value = normalize_mapped_value(mapped_value)
    notes = (notes or "").strip() or None

    if not raw_value:
        raise ValueError("Raw value is required.")

    if not mapped_value:
        raise ValueError("Mapped value is required.")

    now = utc_now_iso()

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM snipeops_mappings
            WHERE source = ? AND field = ? AND raw_value = ?
            """,
            (source, field, raw_value),
        ).fetchone()

        if existing:
            mapping_id = existing["id"]
            conn.execute(
                """
                UPDATE snipeops_mappings
                SET mapped_value = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (mapped_value, notes, now, mapping_id),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO snipeops_mappings (
                    source,
                    field,
                    raw_value,
                    mapped_value,
                    notes,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (source, field, raw_value, mapped_value, notes, now, now),
            )
            mapping_id = cursor.lastrowid

        conn.commit()

    return get_mapping_by_id(mapping_id)


def delete_mapping(mapping_id: int):
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM snipeops_mappings
            WHERE id = ?
            """,
            (mapping_id,),
        )
        conn.commit()


def seed_default_mappings():
    for source, field, raw_value, mapped_value in DEFAULT_OS_VERSION_MAPPINGS:
        try:
            upsert_mapping(
                source=source,
                field=field,
                raw_value=raw_value,
                mapped_value=mapped_value,
                notes="Default Windows OS version mapping.",
            )
        except ValueError:
            continue