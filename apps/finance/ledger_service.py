from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .db import get_connection


TC_MAP = {
    "11": "original_expenditure_budget",
    "12": "original_revenue_budget",
    "13": "adjust_expenditure_budget",
    "14": "adjust_revenue_budget",
    "15": "original_project_budget",
    "16": "adjust_project_budget",
    "17": "add_encumbrance",
    "18": "change_encumbrance",
    "19": "journal_entry",
    "20": "manual_or_void_check",
    "21": "accounts_payable_check",
    "22": "payroll_transaction",
    "23": "add_change_receivable",
    "24": "post_receipts",
    "25": "expenditure_budget_transfer",
    "26": "revenue_budget_transfer",
    "27": "project_budget_transfer",
}

BUDGET_TC = {"11", "13", "25", "27"}
ENCUMBRANCE_TC = {"17", "18"}
EXPENDITURE_TC = {"20", "21"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize_tc(value: Any) -> str | None:
    value = normalize_text(value)
    if not value:
        return None
    first = value.split("-", 1)[0].strip()
    return first if first.isdigit() else value


def normalize_po(value: Any) -> str | None:
    value = normalize_text(value)
    if not value:
        return None
    return value.upper().replace(" ", "")


def parse_money(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    cleaned = str(value).strip().replace("$", "").replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        return Decimal(cleaned or "0").quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def money(value: Any) -> str:
    return str(parse_money(value).quantize(Decimal("0.01")))


def ensure_finance_ledger_schema(conn=None) -> None:
    owns_connection = conn is None
    conn = conn or get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS finance_ledger_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_name TEXT NOT NULL,
                import_run_id INTEGER NULL,
                source_type TEXT NULL,
                source_row_number INTEGER NULL,
                source_hash TEXT NULL UNIQUE,
                fiscal_year_id INTEGER NULL,
                fiscal_year_code TEXT NULL,
                transaction_code TEXT NULL,
                transaction_code_label TEXT NULL,
                ledger_kind TEXT NOT NULL DEFAULT 'other',
                review_status TEXT NOT NULL DEFAULT 'unlinked',
                archive_status TEXT NOT NULL DEFAULT 'active',
                archived_at TEXT NULL,
                title TEXT NULL,
                description TEXT NULL,
                vendor_id INTEGER NULL,
                vendor_code TEXT NULL,
                vendor_name TEXT NULL,
                fund TEXT NULL,
                budget_unit TEXT NULL,
                account_code TEXT NULL,
                po_number TEXT NULL,
                normalized_po_number TEXT NULL,
                purchase_order_id INTEGER NULL,
                purchase_date TEXT NULL,
                budget_amount TEXT NOT NULL DEFAULT '0.00',
                expenditure_amount TEXT NOT NULL DEFAULT '0.00',
                encumbrance_amount TEXT NOT NULL DEFAULT '0.00',
                cumulative_balance TEXT NOT NULL DEFAULT '0.00',
                linked_record_id INTEGER NULL,
                link_confidence INTEGER NOT NULL DEFAULT 0,
                link_reason TEXT NULL,
                raw_json TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_budget_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_name TEXT NOT NULL,
                fiscal_year_id INTEGER NULL,
                fiscal_year_code TEXT NULL,
                fund TEXT NULL,
                budget_unit TEXT NULL,
                account_code TEXT NULL,
                account_title TEXT NULL,
                original_budget TEXT NOT NULL DEFAULT '0.00',
                budget_adjustments TEXT NOT NULL DEFAULT '0.00',
                budget_transfers TEXT NOT NULL DEFAULT '0.00',
                current_budget TEXT NOT NULL DEFAULT '0.00',
                spent_amount TEXT NOT NULL DEFAULT '0.00',
                encumbered_amount TEXT NOT NULL DEFAULT '0.00',
                available_amount TEXT NOT NULL DEFAULT '0.00',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(department_name, fiscal_year_code, fund, budget_unit, account_code)
            );

            CREATE TABLE IF NOT EXISTS finance_purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_name TEXT NOT NULL,
                fiscal_year_id INTEGER NULL,
                fiscal_year_code TEXT NULL,
                po_number TEXT NOT NULL,
                normalized_po_number TEXT NOT NULL,
                vendor_id INTEGER NULL,
                vendor_name TEXT NULL,
                budget_account_id INTEGER NULL,
                account_code TEXT NULL,
                budget_unit TEXT NULL,
                original_encumbrance TEXT NOT NULL DEFAULT '0.00',
                encumbrance_changes TEXT NOT NULL DEFAULT '0.00',
                current_encumbrance TEXT NOT NULL DEFAULT '0.00',
                paid_amount TEXT NOT NULL DEFAULT '0.00',
                remaining_encumbrance TEXT NOT NULL DEFAULT '0.00',
                status TEXT NOT NULL DEFAULT 'open',
                linked_record_id INTEGER NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(department_name, fiscal_year_code, normalized_po_number)
            );

            CREATE TABLE IF NOT EXISTS finance_record_ledger_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                finance_record_id INTEGER NOT NULL,
                ledger_transaction_id INTEGER NOT NULL,
                purchase_order_id INTEGER NULL,
                budget_account_id INTEGER NULL,
                fiscal_year_id INTEGER NULL,
                fiscal_year_code TEXT NULL,
                link_type TEXT NOT NULL DEFAULT 'auto',
                confidence INTEGER NOT NULL DEFAULT 0,
                reason TEXT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(finance_record_id, ledger_transaction_id)
            );

            CREATE TABLE IF NOT EXISTS finance_record_fiscal_year_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                finance_record_id INTEGER NOT NULL,
                fiscal_year_id INTEGER NULL,
                fiscal_year_code TEXT NOT NULL,
                vendor_id INTEGER NULL,
                vendor_name TEXT NULL,
                po_count INTEGER NOT NULL DEFAULT 0,
                po_numbers TEXT NULL,
                budget_accounts TEXT NULL,
                budget_amount TEXT NOT NULL DEFAULT '0.00',
                encumbered_amount TEXT NOT NULL DEFAULT '0.00',
                paid_amount TEXT NOT NULL DEFAULT '0.00',
                remaining_encumbrance TEXT NOT NULL DEFAULT '0.00',
                updated_at TEXT NOT NULL,
                UNIQUE(finance_record_id, fiscal_year_code)
            );

            CREATE INDEX IF NOT EXISTS idx_finance_ledger_department_status
            ON finance_ledger_transactions(department_name, archive_status, review_status);

            CREATE INDEX IF NOT EXISTS idx_finance_ledger_po
            ON finance_ledger_transactions(department_name, fiscal_year_code, normalized_po_number);

            CREATE INDEX IF NOT EXISTS idx_finance_ledger_record
            ON finance_ledger_transactions(linked_record_id, fiscal_year_code);

            CREATE INDEX IF NOT EXISTS idx_finance_po_record
            ON finance_purchase_orders(linked_record_id, fiscal_year_code);

            CREATE INDEX IF NOT EXISTS idx_finance_record_fy_summary
            ON finance_record_fiscal_year_summary(finance_record_id, fiscal_year_code);
            """
        )
        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


def resolve_fiscal_year(conn, purchase_date: str | None) -> dict | None:
    purchase_date = normalize_text(purchase_date)
    if not purchase_date:
        return None

    row = conn.execute(
        """
        SELECT *
        FROM finance_fiscal_years
        WHERE date(?) BETWEEN date(start_date) AND date(end_date)
        ORDER BY year_number DESC
        LIMIT 1
        """,
        (purchase_date,),
    ).fetchone()
    return dict(row) if row else None


def classify_ledger_kind(transaction_code: str | None) -> str:
    if transaction_code in BUDGET_TC:
        return "budget"
    if transaction_code in ENCUMBRANCE_TC:
        return "encumbrance"
    if transaction_code in EXPENDITURE_TC:
        return "expenditure"
    return "other"


def make_source_hash(*, import_run_id: int | None, source_row_number: int | None, row: dict) -> str:
    import hashlib

    normalized_row = {
        str(key).strip().lower(): normalize_text(value)
        for key, value in sorted(row.items(), key=lambda item: str(item[0]).strip().lower())
    }
    payload = {"row": normalized_row}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def upsert_budget_account(conn, *, ledger: dict) -> int | None:
    if ledger["ledger_kind"] != "budget" and not (ledger.get("fund") and ledger.get("budget_unit") and ledger.get("account_code")):
        return None

    now = utc_now_iso()
    key = (
        ledger["department_name"],
        ledger.get("fiscal_year_code"),
        ledger.get("fund"),
        ledger.get("budget_unit"),
        ledger.get("account_code"),
    )
    row = conn.execute(
        """
        SELECT * FROM finance_budget_accounts
        WHERE department_name = ?
          AND COALESCE(fiscal_year_code, '') = COALESCE(?, '')
          AND COALESCE(fund, '') = COALESCE(?, '')
          AND COALESCE(budget_unit, '') = COALESCE(?, '')
          AND COALESCE(account_code, '') = COALESCE(?, '')
        """,
        key,
    ).fetchone()

    if not row:
        cursor = conn.execute(
            """
            INSERT INTO finance_budget_accounts (
                department_name, fiscal_year_id, fiscal_year_code, fund, budget_unit,
                account_code, account_title, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ledger["department_name"], ledger.get("fiscal_year_id"), ledger.get("fiscal_year_code"),
                ledger.get("fund"), ledger.get("budget_unit"), ledger.get("account_code"),
                ledger.get("account_title"), now, now,
            ),
        )
        budget_account_id = cursor.lastrowid
    else:
        budget_account_id = row["id"]

    recalculate_budget_account(conn, budget_account_id)
    return budget_account_id


def recalculate_budget_account(conn, budget_account_id: int) -> None:
    account = conn.execute("SELECT * FROM finance_budget_accounts WHERE id = ?", (budget_account_id,)).fetchone()
    if not account:
        return

    rows = conn.execute(
        """
        SELECT * FROM finance_ledger_transactions
        WHERE department_name = ?
          AND COALESCE(fiscal_year_code, '') = COALESCE(?, '')
          AND COALESCE(fund, '') = COALESCE(?, '')
          AND COALESCE(budget_unit, '') = COALESCE(?, '')
          AND COALESCE(account_code, '') = COALESCE(?, '')
          AND archive_status IN ('active', 'archived')
        """,
        (account["department_name"], account["fiscal_year_code"], account["fund"], account["budget_unit"], account["account_code"]),
    ).fetchall()

    original_budget = Decimal("0.00")
    adjustments = Decimal("0.00")
    transfers = Decimal("0.00")
    spent = Decimal("0.00")

    for row in rows:
        tc = row["transaction_code"]
        budget_amount = parse_money(row["budget_amount"])
        if tc == "11":
            original_budget += budget_amount
        elif tc == "13":
            adjustments += budget_amount
        elif tc in {"25", "27"}:
            transfers += budget_amount
        if tc in EXPENDITURE_TC:
            spent += parse_money(row["expenditure_amount"])

    encumbered = sum((parse_money(row["encumbrance_amount"]) for row in rows if row["transaction_code"] in ENCUMBRANCE_TC), Decimal("0.00"))
    current_budget = original_budget + adjustments + transfers
    available = current_budget - spent - encumbered
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE finance_budget_accounts
        SET original_budget = ?, budget_adjustments = ?, budget_transfers = ?,
            current_budget = ?, spent_amount = ?, encumbered_amount = ?,
            available_amount = ?, updated_at = ?
        WHERE id = ?
        """,
        (money(original_budget), money(adjustments), money(transfers), money(current_budget), money(spent), money(encumbered), money(available), now, budget_account_id),
    )
