from __future__ import annotations

import json
import zlib
from typing import Any

from .ledger_accounting_service import normalize_po
from .ledger_service import money, normalize_text


def build_ledger_match_key(*, ledger: dict[str, Any]) -> str:
    identity = {
        "department_name": normalize_text(ledger.get("department_name")),
        "fiscal_year_code": normalize_text(ledger.get("fiscal_year_code")),
        "transaction_code": normalize_text(ledger.get("transaction_code")),
        "purchase_date": normalize_text(ledger.get("purchase_date")),
        "fund": normalize_text(ledger.get("fund")),
        "budget_unit": normalize_text(ledger.get("budget_unit")),
        "account_code": normalize_text(ledger.get("account_code")),
        "po_number": normalize_text(ledger.get("po_number")),
        "normalized_po_number": normalize_po(ledger.get("po_number")) or normalize_text(ledger.get("normalized_po_number")),
        "vendor_code": normalize_text(ledger.get("vendor_code")),
        "vendor_name": normalize_text(ledger.get("vendor_name")),
        "description": normalize_text(ledger.get("description")),
        "budget_amount": money(ledger.get("budget_amount")),
        "expenditure_amount": money(ledger.get("expenditure_amount")),
        "encumbrance_amount": money(ledger.get("encumbrance_amount")),
    }
    payload = json.dumps(identity, sort_keys=True, default=str)
    checksum = zlib.crc32(payload.encode("utf-8")) & 0xffffffff
    return f"ledger-{checksum:08x}"
