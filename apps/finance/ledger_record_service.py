from __future__ import annotations

from typing import Any

from .ledger_service import money, normalize_text, utc_now_iso


def should_create_record_from_ledger(*, ledger: dict[str, Any], match_confidence: int) -> tuple[bool, str]:
    if match_confidence > 0:
        return False, "Existing record match found."
    if not ledger.get("vendor_id") and not ledger.get("vendor_name"):
        return False, "Vendor is required."
    if not ledger.get("normalized_po_number"):
        return False, "PO number is required."
    if ledger.get("ledger_kind") not in {"encumbrance", "expenditure"}:
        return False, "Only encumbrance and expenditure rows qualify."
    return True, "Vendor and PO are present with no existing record match."


def build_record_title_from_ledger(*, ledger: dict[str, Any]) -> str:
    vendor_name = normalize_text(ledger.get("vendor_name"))
    description = normalize_text(ledger.get("description")) or normalize_text(ledger.get("title"))
    po_number = normalize_text(ledger.get("po_number"))
    if vendor_name and description:
        cleaned = description.title()
        if vendor_name.lower() in cleaned.lower():
            return cleaned
        return f"{vendor_name} - {cleaned}"
    if vendor_name and po_number:
        return f"{vendor_name} - PO {po_number}"
    if description:
        return description.title()
    if vendor_name:
        return vendor_name
    return "Imported Ledger Record"


def create_record_from_ledger(conn, *, ledger: dict[str, Any], created_by_user_id: int | None = None) -> int:
    now = utc_now_iso()
    title = build_record_title_from_ledger(ledger=ledger)
    amount = ledger.get("expenditure_amount") or ledger.get("encumbrance_amount") or ledger.get("budget_amount")
    cursor = conn.execute(
        """
        INSERT INTO finance_records (
            record_type, title, vendor_id, category_id, department_name,
            account_code, po_number, purchase_date, service_start_date,
            use_purchase_date_as_start, term_length, term_unit, expiration_date,
            renewal_date, notify_days_before, notification_recipients, status,
            cost, notes, created_by_user_id, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, 1, NULL, NULL, NULL, NULL, 30, NULL, ?, ?, ?, ?, ?, ?)
        """,
        (
            "renewal", title, ledger.get("vendor_id"), ledger["department_name"],
            normalize_text(ledger.get("account_code")), normalize_text(ledger.get("po_number")),
            normalize_text(ledger.get("purchase_date")), normalize_text(ledger.get("purchase_date")),
            "active", money(amount), "Created from Ledger import.", created_by_user_id, now, now,
        ),
    )
    record_id = cursor.lastrowid
    conn.execute(
        """
        INSERT INTO finance_record_history (
            finance_record_id, event_type, summary, changed_by_user_id, changed_at
        ) VALUES (?, 'created', ?, ?, ?)
        """,
        (record_id, f"Record created from Ledger import: {title}", created_by_user_id, now),
    )
    return record_id
