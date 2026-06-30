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
    # eFinance can show transaction code as 21, 21-1, or 21 - 1.
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
    """Create the ledger-first finance tables.

    These tables sit beside the existing finance_records and finance_transactions
    tables so we can move the importer to a ledger-first workflow without breaking
    the current Records UI.
    """
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
                budget_account_id INTEGER NULL,

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

    payload = {
        "import_run_id": import_run_id,
        "source_row_number": source_row_number,
        "row": row,
    }
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
    encumbered = Decimal("0.00")

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
        if tc in ENCUMBRANCE_TC:
            encumbered += parse_money(row["encumbrance_amount"])

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


def upsert_purchase_order(conn, *, ledger: dict) -> int | None:
    po_number = normalize_po(ledger.get("po_number"))
    if not po_number:
        return None

    now = utc_now_iso()
    row = conn.execute(
        """
        SELECT * FROM finance_purchase_orders
        WHERE department_name = ?
          AND COALESCE(fiscal_year_code, '') = COALESCE(?, '')
          AND normalized_po_number = ?
        """,
        (ledger["department_name"], ledger.get("fiscal_year_code"), po_number),
    ).fetchone()

    if not row:
        cursor = conn.execute(
            """
            INSERT INTO finance_purchase_orders (
                department_name, fiscal_year_id, fiscal_year_code, po_number,
                normalized_po_number, vendor_id, vendor_name, budget_account_id,
                account_code, budget_unit, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ledger["department_name"], ledger.get("fiscal_year_id"), ledger.get("fiscal_year_code"),
                ledger.get("po_number"), po_number, ledger.get("vendor_id"), ledger.get("vendor_name"),
                ledger.get("budget_account_id"), ledger.get("account_code"), ledger.get("budget_unit"), now, now,
            ),
        )
        purchase_order_id = cursor.lastrowid
    else:
        purchase_order_id = row["id"]
        conn.execute(
            """
            UPDATE finance_purchase_orders
            SET vendor_id = COALESCE(vendor_id, ?),
                vendor_name = COALESCE(vendor_name, ?),
                budget_account_id = COALESCE(budget_account_id, ?),
                account_code = COALESCE(account_code, ?),
                budget_unit = COALESCE(budget_unit, ?),
                updated_at = ?
            WHERE id = ?
            """,
            (ledger.get("vendor_id"), ledger.get("vendor_name"), ledger.get("budget_account_id"), ledger.get("account_code"), ledger.get("budget_unit"), now, purchase_order_id),
        )

    recalculate_purchase_order(conn, purchase_order_id)
    return purchase_order_id


def recalculate_purchase_order(conn, purchase_order_id: int) -> None:
    po = conn.execute("SELECT * FROM finance_purchase_orders WHERE id = ?", (purchase_order_id,)).fetchone()
    if not po:
        return

    rows = conn.execute(
        """
        SELECT * FROM finance_ledger_transactions
        WHERE department_name = ?
          AND COALESCE(fiscal_year_code, '') = COALESCE(?, '')
          AND normalized_po_number = ?
          AND archive_status IN ('active', 'archived')
        """,
        (po["department_name"], po["fiscal_year_code"], po["normalized_po_number"]),
    ).fetchall()

    original = Decimal("0.00")
    changes = Decimal("0.00")
    paid = Decimal("0.00")

    for row in rows:
        tc = row["transaction_code"]
        if tc == "17":
            original += parse_money(row["encumbrance_amount"])
        elif tc == "18":
            changes += parse_money(row["encumbrance_amount"])
        elif tc in EXPENDITURE_TC:
            paid += parse_money(row["expenditure_amount"])

    current = original + changes
    remaining = current - paid
    status = "closed" if current != 0 and remaining <= 0 else "open"
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE finance_purchase_orders
        SET original_encumbrance = ?, encumbrance_changes = ?, current_encumbrance = ?,
            paid_amount = ?, remaining_encumbrance = ?, status = ?, updated_at = ?
        WHERE id = ?
        """,
        (money(original), money(changes), money(current), money(paid), money(remaining), status, now, purchase_order_id),
    )


def find_record_match(conn, *, ledger: dict) -> tuple[int | None, int, str | None]:
    """Return (record_id, confidence, reason) for high-confidence ledger linking."""
    department_name = ledger["department_name"]
    normalized_po = normalize_po(ledger.get("po_number"))
    vendor_id = ledger.get("vendor_id")
    account_code = normalize_text(ledger.get("account_code"))
    description = (normalize_text(ledger.get("description")) or normalize_text(ledger.get("title")) or "").lower()

    if normalized_po:
        row = conn.execute(
            """
            SELECT id FROM finance_records
            WHERE department_name = ?
              AND UPPER(REPLACE(COALESCE(po_number, ''), ' ', '')) = ?
              AND status NOT IN ('deleted')
            ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, id DESC
            LIMIT 1
            """,
            (department_name, normalized_po),
        ).fetchone()
        if row:
            return row["id"], 100, "Exact PO match"

    if vendor_id and account_code and description:
        rows = conn.execute(
            """
            SELECT id, title
            FROM finance_records
            WHERE department_name = ?
              AND vendor_id = ?
              AND COALESCE(account_code, '') = ?
              AND status NOT IN ('deleted')
            """,
            (department_name, vendor_id, account_code),
        ).fetchall()
        matches = [row for row in rows if row["title"] and row["title"].lower() in description]
        if len(matches) == 1:
            return matches[0]["id"], 90, "Vendor, account, and title keyword match"

    return None, 0, None


def link_ledger_to_record(conn, *, ledger_transaction_id: int, record_id: int, confidence: int, reason: str | None) -> None:
    now = utc_now_iso()
    ledger = conn.execute("SELECT * FROM finance_ledger_transactions WHERE id = ?", (ledger_transaction_id,)).fetchone()
    if not ledger:
        return

    conn.execute(
        """
        UPDATE finance_ledger_transactions
        SET linked_record_id = ?, link_confidence = ?, link_reason = ?,
            review_status = 'linked', updated_at = ?
        WHERE id = ?
        """,
        (record_id, confidence, reason, now, ledger_transaction_id),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO finance_record_ledger_links (
            finance_record_id, ledger_transaction_id, purchase_order_id, budget_account_id,
            fiscal_year_id, fiscal_year_code, link_type, confidence, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'auto', ?, ?, ?)
        """,
        (record_id, ledger_transaction_id, ledger["purchase_order_id"], ledger["budget_account_id"], ledger["fiscal_year_id"], ledger["fiscal_year_code"], confidence, reason, now),
    )
    if ledger["purchase_order_id"]:
        conn.execute(
            "UPDATE finance_purchase_orders SET linked_record_id = ?, updated_at = ? WHERE id = ? AND linked_record_id IS NULL",
            (record_id, now, ledger["purchase_order_id"]),
        )
    refresh_record_fiscal_year_summary(conn, record_id, ledger["fiscal_year_code"])


def refresh_record_fiscal_year_summary(conn, record_id: int, fiscal_year_code: str | None) -> None:
    fiscal_year_code = normalize_text(fiscal_year_code)
    if not fiscal_year_code:
        return

    rows = conn.execute(
        """
        SELECT * FROM finance_ledger_transactions
        WHERE linked_record_id = ?
          AND fiscal_year_code = ?
          AND archive_status IN ('active', 'archived')
        """,
        (record_id, fiscal_year_code),
    ).fetchall()
    if not rows:
        return

    po_numbers = sorted({row["po_number"] for row in rows if row["po_number"]})
    budget_accounts = sorted({"/".join(filter(None, [row["fund"], row["budget_unit"], row["account_code"]])) for row in rows if row["account_code"]})
    vendor_id = next((row["vendor_id"] for row in rows if row["vendor_id"]), None)
    vendor_name = next((row["vendor_name"] for row in rows if row["vendor_name"]), None)

    budget_amount = sum((parse_money(row["budget_amount"]) for row in rows), Decimal("0.00"))
    encumbered = sum((parse_money(row["encumbrance_amount"]) for row in rows if row["transaction_code"] in ENCUMBRANCE_TC), Decimal("0.00"))
    paid = sum((parse_money(row["expenditure_amount"]) for row in rows if row["transaction_code"] in EXPENDITURE_TC), Decimal("0.00"))
    remaining = encumbered - paid
    now = utc_now_iso()

    conn.execute(
        """
        INSERT INTO finance_record_fiscal_year_summary (
            finance_record_id, fiscal_year_id, fiscal_year_code, vendor_id, vendor_name,
            po_count, po_numbers, budget_accounts, budget_amount, encumbered_amount,
            paid_amount, remaining_encumbrance, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(finance_record_id, fiscal_year_code)
        DO UPDATE SET
            vendor_id = excluded.vendor_id,
            vendor_name = excluded.vendor_name,
            po_count = excluded.po_count,
            po_numbers = excluded.po_numbers,
            budget_accounts = excluded.budget_accounts,
            budget_amount = excluded.budget_amount,
            encumbered_amount = excluded.encumbered_amount,
            paid_amount = excluded.paid_amount,
            remaining_encumbrance = excluded.remaining_encumbrance,
            updated_at = excluded.updated_at
        """,
        (record_id, rows[0]["fiscal_year_id"], fiscal_year_code, vendor_id, vendor_name, len(po_numbers), ", ".join(po_numbers), ", ".join(budget_accounts), money(budget_amount), money(encumbered), money(paid), money(remaining), now),
    )


def close_fiscal_year_ledgers(*, fiscal_year_code: str, department_name: str | None = None) -> dict:
    """Archive ledger rows for a closed fiscal year while keeping record summaries."""
    fiscal_year_code = normalize_text(fiscal_year_code)
    if not fiscal_year_code:
        raise ValueError("fiscal_year_code is required")

    where = ["fiscal_year_code = ?", "archive_status = 'active'"]
    params: list[Any] = [fiscal_year_code]
    if department_name:
        where.append("department_name = ?")
        params.append(department_name)

    now = utc_now_iso()
    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        record_rows = conn.execute(
            f"SELECT DISTINCT linked_record_id FROM finance_ledger_transactions WHERE {' AND '.join(where)} AND linked_record_id IS NOT NULL",
            params,
        ).fetchall()
        conn.execute(
            f"""
            UPDATE finance_ledger_transactions
            SET archive_status = 'archived', archived_at = ?, updated_at = ?
            WHERE {' AND '.join(where)}
            """,
            [now, now, *params],
        )
        changed = conn.total_changes
        for row in record_rows:
            refresh_record_fiscal_year_summary(conn, row["linked_record_id"], fiscal_year_code)
        conn.commit()

    return {"archived": changed, "fiscal_year_code": fiscal_year_code}
