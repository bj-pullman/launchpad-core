from __future__ import annotations

from collections import Counter
from typing import Any

from .db import get_connection
from .ledger_import_service import _mapped_row, _should_skip_ledger_row
from .ledger_service import normalize_text, resolve_fiscal_year
from .service import (
    find_vendor_for_import,
    get_import_profile_fields,
    get_import_run_by_id,
    read_import_rows,
)
from .transaction_code_service import get_transaction_code_info, normalize_transaction_code


def _vendor_key(vendor_name: str | None, vendor_code: str | None) -> str | None:
    vendor_name = normalize_text(vendor_name)
    vendor_code = normalize_text(vendor_code)
    if vendor_code:
        return f"code:{vendor_code}"
    if vendor_name:
        return f"name:{vendor_name.lower()}"
    return None


def validate_ledger_import(
    *,
    run_id: int,
    profile_id: int | None = None,
    default_department_name: str | None = None,
    preview_limit: int = 20,
) -> dict[str, Any]:
    """Validate an ERP ledger import without using the legacy transactions pipeline."""
    run = get_import_run_by_id(run_id)
    if not run:
        raise ValueError("Import run not found")

    rows = read_import_rows(run["stored_filename"])
    mappings = get_import_profile_fields(profile_id or run.get("profile_id")) if (profile_id or run.get("profile_id")) else []

    total_rows = len(rows)
    ignored_rows = 0
    error_rows = 0
    preview_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    transaction_codes: Counter[str] = Counter()
    ledger_kinds: Counter[str] = Counter()
    fiscal_years: Counter[str] = Counter()
    budget_accounts: set[tuple[str | None, str | None, str | None, str | None]] = set()
    purchase_orders: set[str] = set()
    vendors: dict[str, tuple[str | None, str | None]] = {}
    vendors_to_create: dict[str, tuple[str | None, str | None]] = {}

    with get_connection() as conn:
        for index, row in enumerate(rows, start=2):
            try:
                mapped = _mapped_row(row, mappings, index)
                if default_department_name:
                    mapped["department_name"] = default_department_name

                if _should_skip_ledger_row(mapped):
                    ignored_rows += 1
                    continue

                transaction_code = normalize_transaction_code(mapped.get("transaction_code"))
                tc_info = get_transaction_code_info(transaction_code)
                ledger_kind = tc_info["ledger_kind"]
                purchase_date = normalize_text(mapped.get("purchase_date"))
                fiscal_year = resolve_fiscal_year(conn, purchase_date)

                if transaction_code:
                    transaction_codes[transaction_code] += 1
                ledger_kinds[ledger_kind] += 1
                if fiscal_year:
                    fiscal_years[fiscal_year["code"]] += 1

                fund = normalize_text(mapped.get("fund"))
                budget_unit = normalize_text(mapped.get("budget_unit"))
                account_code = normalize_text(mapped.get("account_code"))
                department_name = normalize_text(mapped.get("department_name")) or normalize_text(default_department_name)
                if fund or budget_unit or account_code:
                    budget_accounts.add((department_name, fund, budget_unit, account_code))

                po_number = normalize_text(mapped.get("po_number"))
                if po_number:
                    purchase_orders.add(po_number)

                vendor_name = normalize_text(mapped.get("vendor_name"))
                vendor_code = normalize_text(mapped.get("vendor_code"))
                key = _vendor_key(vendor_name, vendor_code)
                if key:
                    vendors[key] = (vendor_name, vendor_code)
                    existing_vendor = find_vendor_for_import(vendor_name=vendor_name, vendor_code=vendor_code)
                    if not existing_vendor:
                        vendors_to_create[key] = (vendor_name, vendor_code)

                if len(preview_rows) < preview_limit:
                    preview = dict(mapped)
                    preview["transaction_code"] = transaction_code
                    preview["transaction_type"] = ledger_kind
                    preview["ledger_kind"] = ledger_kind
                    preview["transaction_code_label"] = tc_info["label"]
                    preview["fiscal_year_code"] = fiscal_year["code"] if fiscal_year else None
                    preview_rows.append(preview)

            except Exception as exc:
                error_rows += 1
                errors.append({
                    "row_number": index,
                    "error_message": str(exc),
                })

    valid_rows = total_rows - ignored_rows - error_rows
    return {
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "ready_to_import_rows": valid_rows,
        "ignored_rows": ignored_rows,
        "duplicate_rows": 0,
        "error_rows": error_rows,
        "errors": errors,
        "vendors_to_create": len(vendors_to_create),
        "preview_rows": preview_rows,
        "category_suggestions": [],
        "transaction_codes": dict(transaction_codes),
        "ledger_kinds": dict(ledger_kinds),
        "fiscal_years": dict(fiscal_years),
        "budget_accounts_found": len(budget_accounts),
        "purchase_orders_found": len(purchase_orders),
        "vendors_found": len(vendors),
    }
