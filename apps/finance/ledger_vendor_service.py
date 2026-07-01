from __future__ import annotations

from typing import Any

from .ledger_service import normalize_text, utc_now_iso
from .service import normalize_vendor_name, suggest_vendor_friendly_name


def find_vendor_for_ledger_import(
    conn,
    *,
    vendor_name: str | None = None,
    vendor_code: str | None = None,
) -> dict[str, Any] | None:
    vendor_name = normalize_vendor_name(vendor_name)
    vendor_code = normalize_text(vendor_code)

    if vendor_code:
        row = conn.execute(
            """
            SELECT *
            FROM finance_vendors
            WHERE vendor_code = ?
            LIMIT 1
            """,
            (vendor_code,),
        ).fetchone()
        if row:
            return dict(row)

    if vendor_name:
        row = conn.execute(
            """
            SELECT *
            FROM finance_vendors
            WHERE LOWER(TRIM(vendor_name)) = LOWER(TRIM(?))
            LIMIT 1
            """,
            (vendor_name,),
        ).fetchone()
        if row:
            return dict(row)

    return None


def get_or_create_vendor_for_ledger_import(
    conn,
    *,
    vendor_name: str | None = None,
    vendor_code: str | None = None,
) -> tuple[int | None, bool]:
    vendor_name = normalize_vendor_name(vendor_name)
    vendor_code = normalize_text(vendor_code)

    if not vendor_name and not vendor_code:
        return None, False

    existing = find_vendor_for_ledger_import(
        conn,
        vendor_name=vendor_name,
        vendor_code=vendor_code,
    )
    if existing:
        return existing["id"], False

    if not vendor_name:
        return None, False

    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO finance_vendors (
            vendor_name,
            friendly_name,
            vendor_code,
            website,
            main_phone,
            billing_email,
            support_email,
            sales_contact_name,
            sales_contact_email,
            is_active,
            notes,
            created_at,
            updated_at,
            status,
            deleted_at
        ) VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, 1, NULL, ?, ?, 'active', NULL)
        """,
        (
            vendor_name,
            suggest_vendor_friendly_name(vendor_name),
            vendor_code,
            now,
            now,
        ),
    )
    return cursor.lastrowid, True
