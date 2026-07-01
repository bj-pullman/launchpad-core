from __future__ import annotations

from decimal import Decimal
from typing import Any

from .ledger_accounting_service import normalize_po
from .ledger_service import money, normalize_text, parse_money, utc_now_iso


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


def _best_amount_from_ledger(ledger: dict[str, Any]) -> Decimal:
    paid = parse_money(ledger.get("expenditure_amount"))
    encumbered = parse_money(ledger.get("encumbrance_amount"))
    budget = parse_money(ledger.get("budget_amount"))

    if paid > 0:
        return paid
    if encumbered > 0:
        return encumbered
    if budget > 0:
        return budget
    return Decimal("0.00")


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
    amount = _best_amount_from_ledger(ledger)
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


def update_record_financials_from_ledger(
    conn,
    *,
    record_id: int,
    changed_by_user_id: int | None = None,
) -> None:
    """Refresh a Finance Record's cost and core fields from linked Ledger rows.

    Cost should represent what the record cost the district. Prefer actual paid
    amount when available. If no payment has posted yet, fall back to authorized
    positive encumbrance. Never use remaining encumbrance as the record cost.
    """
    record = conn.execute(
        "SELECT * FROM finance_records WHERE id = ?",
        (record_id,),
    ).fetchone()
    if not record:
        return

    rows = conn.execute(
        """
        SELECT *
        FROM finance_ledger_transactions
        WHERE linked_record_id = ?
          AND archive_status IN ('active', 'archived')
        ORDER BY purchase_date ASC, id ASC
        """,
        (record_id,),
    ).fetchall()
    if not rows:
        return

    paid = Decimal("0.00")
    authorized = Decimal("0.00")
    first_purchase_date = None
    base_po_number = None
    account_code = None
    vendor_id = None

    for row in rows:
        if not first_purchase_date and row["purchase_date"]:
            first_purchase_date = row["purchase_date"]
        if not base_po_number and row["po_number"]:
            base_po_number = normalize_po(row["po_number"])
        if not account_code and row["account_code"]:
            account_code = row["account_code"]
        if not vendor_id and row["vendor_id"]:
            vendor_id = row["vendor_id"]

        if row["transaction_code"] in {"20", "21", "22"}:
            paid += parse_money(row["expenditure_amount"])
        if row["transaction_code"] in {"17", "18"}:
            encumbrance = parse_money(row["encumbrance_amount"])
            if encumbrance > 0:
                authorized += encumbrance

    new_cost = paid if paid > 0 else authorized
    if new_cost < 0:
        new_cost = Decimal("0.00")

    old_cost = parse_money(record["cost"])
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE finance_records
        SET cost = ?,
            vendor_id = COALESCE(vendor_id, ?),
            account_code = COALESCE(account_code, ?),
            po_number = COALESCE(po_number, ?),
            purchase_date = COALESCE(purchase_date, ?),
            service_start_date = COALESCE(service_start_date, ?),
            updated_at = ?
        WHERE id = ?
        """,
        (
            money(new_cost),
            vendor_id,
            account_code,
            base_po_number,
            first_purchase_date,
            first_purchase_date,
            now,
            record_id,
        ),
    )

    if old_cost != new_cost:
        conn.execute(
            """
            INSERT INTO finance_record_history (
                finance_record_id, event_type, summary, changed_by_user_id, changed_at
            ) VALUES (?, 'updated', ?, ?, ?)
            """,
            (
                record_id,
                f"Record cost refreshed from linked Ledger activity: ${money(old_cost)} to ${money(new_cost)}.",
                changed_by_user_id,
                now,
            ),
        )
