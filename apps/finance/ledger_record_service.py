from __future__ import annotations

from typing import Any

from .ledger_accounting_service import normalize_po
from .ledger_service import money, normalize_text, utc_now_iso


RENEWAL_TERMS = {
    "ANNUAL",
    "RENEWAL",
    "SUBSCRIPTION",
    "SITE LICENSE",
    "LICENSE",
    "LICENCE",
    "SOFTWARE",
}

SERVICE_TERMS = {
    "SERVICE AGREEMENT",
    "SUPPORT",
    "MAINTENANCE",
}

TRAINING_TERMS = {
    "CONFERENCE",
    "TRAINING",
    "REGISTRATION",
}

HARDWARE_TERMS = {
    "LAPTOP",
    "CHROMEBOOK",
    "COMPUTER",
    "MONITOR",
    "PRINTER",
    "PROJECTOR",
    "SWITCH",
    "SERVER",
    "CABLE",
}


def _ledger_text(ledger: dict[str, Any]) -> str:
    parts = [
        normalize_text(ledger.get("title")),
        normalize_text(ledger.get("description")),
        normalize_text(ledger.get("vendor_name")),
    ]
    return " ".join(part for part in parts if part).upper()


def classify_record_type_from_ledger(*, ledger: dict[str, Any]) -> str:
    text = _ledger_text(ledger=ledger)

    if "BLANKET PO" in text:
        return "blanket_po"
    if any(term in text for term in RENEWAL_TERMS):
        if "LICENSE" in text or "LICENCE" in text or "SOFTWARE" in text:
            return "software_license"
        if "SUBSCRIPTION" in text:
            return "subscription"
        return "renewal"
    if any(term in text for term in SERVICE_TERMS):
        if "MAINTENANCE" in text:
            return "maintenance_agreement"
        return "service_agreement"
    if any(term in text for term in TRAINING_TERMS):
        return "training_conference"
    if any(term in text for term in HARDWARE_TERMS):
        return "hardware"
    if "MEMBERSHIP" in text or "DUES" in text:
        return "membership"
    if "LEASE" in text:
        return "lease"
    if "INSURANCE" in text:
        return "insurance"

    return "one_time_purchase"


def should_create_record_from_ledger(*, ledger: dict[str, Any], match_confidence: int) -> tuple[bool, str]:
    if match_confidence > 0:
        return False, "Existing record match found."
    if not ledger.get("vendor_id") and not ledger.get("vendor_name"):
        return False, "Vendor is required."
    if not ledger.get("normalized_po_number"):
        return False, "Base PO number is required."
    if ledger.get("ledger_kind") != "encumbrance" or ledger.get("transaction_code") != "17":
        return False, "Only original encumbrance rows create records automatically."
    return True, "Vendor and base PO are present on an original encumbrance with no existing record match."


def build_record_title_from_ledger(*, ledger: dict[str, Any]) -> str:
    vendor_name = normalize_text(ledger.get("vendor_name"))
    description = normalize_text(ledger.get("description")) or normalize_text(ledger.get("title"))
    po_number = normalize_po(ledger.get("po_number")) or normalize_text(ledger.get("po_number"))
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
    record_type = classify_record_type_from_ledger(ledger=ledger)
    amount = ledger.get("expenditure_amount") or ledger.get("encumbrance_amount") or ledger.get("budget_amount")
    base_po_number = normalize_po(ledger.get("po_number")) or normalize_text(ledger.get("po_number"))
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
            record_type, title, ledger.get("vendor_id"), ledger["department_name"],
            normalize_text(ledger.get("account_code")), base_po_number,
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
        (record_id, f"Record created from Ledger import as {record_type}: {title}", created_by_user_id, now),
    )
    return record_id
