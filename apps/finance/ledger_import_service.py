from __future__ import annotations

import json
from typing import Any

from .db import get_connection
from .ledger_service import (
    ensure_finance_ledger_schema,
    find_record_match,
    link_ledger_to_record,
    make_source_hash,
    money,
    normalize_po,
    normalize_text,
    resolve_fiscal_year,
    upsert_budget_account,
    upsert_purchase_order,
    utc_now_iso,
)
from .service import (
    apply_import_mapping,
    get_import_profile_fields,
    get_import_run_by_id,
    get_or_create_vendor_for_import,
    log_import_run_error,
    normalize_import_vendor_fields,
    read_import_rows,
    update_import_run_results,
)
from .transaction_code_service import get_transaction_code_info, normalize_transaction_code


HEADER_ALIASES = {
    "transaction_code": ["T/C", "TC", "TRANSACTION CODE", "REFERENCE", "REF"],
    "fund": ["FUND"],
    "budget_unit": ["BUDGET UNIT", "BUDGET UNIT TITLE", "FSOF"],
    "account_code": ["ACCOUNT", "ACCOUNT CODE", "OBJECT"],
    "account_title": ["ACCOUNT TITLE", "OBJECT TITLE"],
    "purchase_date": ["DATE", "TRANSACTION DATE"],
    "po_number": ["PURCHASE O", "PURCHASE ORDER", "PO", "P.O.", "P.O. NUMBER"],
    "vendor_name": ["VENDOR", "VENDOR NAME"],
    "vendor_code": ["VENDOR CODE"],
    "description": ["DESCRIPTION", "DESC"],
    "budget_amount": ["BUDGET", "BUDGET AMOUNT"],
    "expenditure_amount": ["EXPENDITURES", "EXPENDITURE", "ACTUAL", "ACTUALS"],
    "encumbrance_amount": ["ENCUMBRANCES", "ENCUMBRANCE", "ENCUMBERED"],
    "cumulative_balance": ["CUMULATIVE BALANCE", "BALANCE"],
}


def _source_value(row: dict[str, Any], field_name: str) -> Any:
    aliases = HEADER_ALIASES.get(field_name, [])
    for alias in aliases:
        if alias in row:
            return row.get(alias)
    lower_lookup = {str(k).strip().lower(): k for k in row.keys()}
    for alias in aliases:
        key = lower_lookup.get(alias.lower())
        if key is not None:
            return row.get(key)
    return None


def _apply_loose_mapping(row: dict[str, Any]) -> dict[str, Any]:
    return {field: _source_value(row, field) for field in HEADER_ALIASES.keys()}


def _mapped_row(row: dict[str, Any], mappings: list[dict], row_number: int) -> dict[str, Any]:
    if mappings:
        mapped = apply_import_mapping(row, mappings, row_number)
    else:
        mapped = _apply_loose_mapping(row)

    loose = _apply_loose_mapping(row)
    for key, value in loose.items():
        mapped.setdefault(key, value)

    return normalize_import_vendor_fields(mapped)


def _build_title(mapped: dict[str, Any], row_number: int) -> str:
    description = normalize_text(mapped.get("description"))
    vendor_name = normalize_text(mapped.get("vendor_name"))
    po_number = normalize_text(mapped.get("po_number"))
    account_code = normalize_text(mapped.get("account_code"))

    if description:
        return description.title()
    if vendor_name and po_number:
        return f"{vendor_name} - PO {po_number}"
    if vendor_name and account_code:
        return f"{vendor_name} - Account {account_code}"
    if account_code:
        return f"Account {account_code}"
    return f"Ledger Row {row_number}"


def _should_skip_ledger_row(mapped: dict[str, Any]) -> bool:
    description = (normalize_text(mapped.get("description")) or "").upper()
    fund = (normalize_text(mapped.get("fund")) or "").upper()

    if fund.startswith("TOTAL ") or description.startswith("TOTAL "):
        return True
    if description == "BEGINNING BALANCE":
        return True
    return False


def insert_ledger_transaction(conn, *, ledger: dict[str, Any]) -> tuple[int | None, bool]:
    existing = conn.execute(
        "SELECT id FROM finance_ledger_transactions WHERE source_hash = ?",
        (ledger["source_hash"],),
    ).fetchone()
    if existing:
        return existing["id"], False

    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO finance_ledger_transactions (
            department_name, import_run_id, source_type, source_row_number, source_hash,
            fiscal_year_id, fiscal_year_code, transaction_code, transaction_code_label,
            ledger_kind, review_status, archive_status, title, description,
            vendor_id, vendor_code, vendor_name, fund, budget_unit, account_code,
            budget_account_id, po_number, normalized_po_number, purchase_order_id,
            purchase_date, budget_amount, expenditure_amount, encumbrance_amount,
            cumulative_balance, raw_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unlinked', 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ledger["department_name"], ledger.get("import_run_id"), ledger.get("source_type"),
            ledger.get("source_row_number"), ledger.get("source_hash"), ledger.get("fiscal_year_id"),
            ledger.get("fiscal_year_code"), ledger.get("transaction_code"), ledger.get("transaction_code_label"),
            ledger.get("ledger_kind"), ledger.get("title"), ledger.get("description"), ledger.get("vendor_id"),
            ledger.get("vendor_code"), ledger.get("vendor_name"), ledger.get("fund"), ledger.get("budget_unit"),
            ledger.get("account_code"), ledger.get("budget_account_id"), ledger.get("po_number"),
            ledger.get("normalized_po_number"), ledger.get("purchase_order_id"), ledger.get("purchase_date"),
            money(ledger.get("budget_amount")), money(ledger.get("expenditure_amount")),
            money(ledger.get("encumbrance_amount")), money(ledger.get("cumulative_balance")),
            ledger.get("raw_json"), now, now,
        ),
    )
    return cursor.lastrowid, True


def execute_ledger_import(
    *,
    run_id: int,
    profile_id: int | None = None,
    default_department_name: str | None = None,
    created_by_user_id: int | None = None,
) -> dict:
    """Import an ERP audit-trail file into the ledger-first tables."""
    run = get_import_run_by_id(run_id)
    if not run:
        raise ValueError("Import run not found")

    rows = read_import_rows(run["stored_filename"])
    mappings = get_import_profile_fields(profile_id or run.get("profile_id")) if (profile_id or run.get("profile_id")) else []

    total_rows = len(rows)
    inserted_rows = 0
    duplicate_rows = 0
    skipped_rows = 0
    error_rows = 0
    budget_accounts_updated: set[int] = set()
    purchase_orders_updated: set[int] = set()
    linked_rows = 0
    vendors_created = 0
    known_transaction_codes: set[str] = set()
    unknown_transaction_codes: set[str] = set()

    update_import_run_results(
        run_id,
        status="running",
        total_rows=total_rows,
        created_rows=0,
        updated_rows=0,
        skipped_rows=0,
        error_rows=0,
        run_notes="Ledger import started.",
        completed=False,
    )

    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)

        for index, row in enumerate(rows, start=2):
            try:
                mapped = _mapped_row(row, mappings, index)
                if default_department_name:
                    mapped["department_name"] = default_department_name

                department_name = normalize_text(mapped.get("department_name")) or normalize_text(default_department_name)
                if not department_name:
                    raise ValueError("department_name is required for ledger import")

                if _should_skip_ledger_row(mapped):
                    skipped_rows += 1
                    continue

                transaction_code = normalize_transaction_code(mapped.get("transaction_code"))
                transaction_code_info = get_transaction_code_info(transaction_code)
                ledger_kind = transaction_code_info["ledger_kind"]
                if transaction_code_info.get("is_known") and transaction_code:
                    known_transaction_codes.add(transaction_code)
                elif transaction_code:
                    unknown_transaction_codes.add(transaction_code)

                purchase_date = normalize_text(mapped.get("purchase_date"))
                fiscal_year = resolve_fiscal_year(conn, purchase_date)

                vendor_id = None
                vendor_was_created = False
                vendor_name = normalize_text(mapped.get("vendor_name"))
                vendor_code = normalize_text(mapped.get("vendor_code"))
                if vendor_name or vendor_code:
                    vendor_id, vendor_was_created = get_or_create_vendor_for_import(
                        vendor_name=vendor_name,
                        vendor_code=vendor_code,
                    )
                    if vendor_was_created:
                        vendors_created += 1

                raw_payload = {
                    "source_row": row,
                    "transaction_code_info": transaction_code_info,
                }

                ledger = {
                    "department_name": department_name,
                    "import_run_id": run_id,
                    "source_type": run.get("source_type") or "erp_audit_trail",
                    "source_row_number": index,
                    "source_hash": make_source_hash(import_run_id=run_id, source_row_number=index, row=row),
                    "fiscal_year_id": fiscal_year["id"] if fiscal_year else None,
                    "fiscal_year_code": fiscal_year["code"] if fiscal_year else None,
                    "transaction_code": transaction_code,
                    "transaction_code_label": transaction_code_info["label"],
                    "ledger_kind": ledger_kind,
                    "title": _build_title(mapped, index),
                    "description": normalize_text(mapped.get("description")),
                    "vendor_id": vendor_id,
                    "vendor_code": vendor_code,
                    "vendor_name": vendor_name,
                    "fund": normalize_text(mapped.get("fund")),
                    "budget_unit": normalize_text(mapped.get("budget_unit")),
                    "account_code": normalize_text(mapped.get("account_code")),
                    "account_title": normalize_text(mapped.get("account_title")),
                    "po_number": normalize_text(mapped.get("po_number")),
                    "normalized_po_number": normalize_po(mapped.get("po_number")),
                    "purchase_date": purchase_date,
                    "budget_amount": mapped.get("budget_amount"),
                    "expenditure_amount": mapped.get("expenditure_amount"),
                    "encumbrance_amount": mapped.get("encumbrance_amount"),
                    "cumulative_balance": mapped.get("cumulative_balance"),
                    "raw_json": json.dumps(raw_payload, default=str),
                }

                budget_account_id = upsert_budget_account(conn, ledger=ledger)
                ledger["budget_account_id"] = budget_account_id
                if budget_account_id:
                    budget_accounts_updated.add(budget_account_id)

                purchase_order_id = upsert_purchase_order(conn, ledger=ledger)
                ledger["purchase_order_id"] = purchase_order_id
                if purchase_order_id:
                    purchase_orders_updated.add(purchase_order_id)

                ledger_id, was_inserted = insert_ledger_transaction(conn, ledger=ledger)
                if was_inserted:
                    inserted_rows += 1
                else:
                    duplicate_rows += 1

                if ledger_id:
                    if budget_account_id:
                        from .ledger_service import recalculate_budget_account
                        recalculate_budget_account(conn, budget_account_id)
                    if purchase_order_id:
                        from .ledger_service import recalculate_purchase_order
                        recalculate_purchase_order(conn, purchase_order_id)

                    record_id, confidence, reason = find_record_match(conn, ledger=ledger)
                    if record_id and confidence >= 90:
                        link_ledger_to_record(
                            conn,
                            ledger_transaction_id=ledger_id,
                            record_id=record_id,
                            confidence=confidence,
                            reason=reason,
                        )
                        linked_rows += 1

            except Exception as exc:
                error_rows += 1
                log_import_run_error(
                    run_id=run_id,
                    row_number=index,
                    source_identifier=row.get(next(iter(row.keys()), ""), "") if row else None,
                    error_message=str(exc),
                )

        conn.commit()

    run_notes = (
        f"Ledger import completed. Inserted: {inserted_rows}, Duplicates: {duplicate_rows}, "
        f"Linked to records: {linked_rows}, Budget accounts updated: {len(budget_accounts_updated)}, "
        f"Purchase orders updated: {len(purchase_orders_updated)}, Vendors created: {vendors_created}, "
        f"Known T/C: {len(known_transaction_codes)}, Unknown T/C: {len(unknown_transaction_codes)}, "
        f"Skipped: {skipped_rows}, Errors: {error_rows}."
    )
    final_status = "completed"
    if error_rows and not inserted_rows:
        final_status = "completed_with_errors"
    elif error_rows:
        final_status = "completed_with_warnings"

    update_import_run_results(
        run_id,
        status=final_status,
        total_rows=total_rows,
        created_rows=inserted_rows,
        updated_rows=linked_rows,
        skipped_rows=skipped_rows + duplicate_rows,
        error_rows=error_rows,
        run_notes=run_notes,
        completed=True,
    )

    return {
        "total_rows": total_rows,
        "inserted_rows": inserted_rows,
        "duplicate_rows": duplicate_rows,
        "linked_rows": linked_rows,
        "budget_accounts_updated": len(budget_accounts_updated),
        "purchase_orders_updated": len(purchase_orders_updated),
        "vendors_created": vendors_created,
        "known_transaction_codes": sorted(known_transaction_codes),
        "unknown_transaction_codes": sorted(unknown_transaction_codes),
        "skipped_rows": skipped_rows,
        "error_rows": error_rows,
        "status": final_status,
        "run_notes": run_notes,
    }
