from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from .ledger_service import (
    ENCUMBRANCE_TC,
    EXPENDITURE_TC,
    money,
    normalize_text,
    parse_money,
    utc_now_iso,
)


def parse_ledger_date_for_sql(value: Any) -> str | None:
    value = normalize_text(value)
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def normalize_po(value: Any) -> str | None:
    value = normalize_text(value)
    if not value:
        return None
    value = value.upper().replace(" ", "")
    match = re.match(r"^(.+?)-(\d{1,3})$", value)
    if match:
        return match.group(1)
    return value


def po_line_item(value: Any) -> str | None:
    value = normalize_text(value)
    if not value:
        return None
    value = value.upper().replace(" ", "")
    match = re.match(r"^.+?-(\d{1,3})$", value)
    if match:
        return match.group(1).zfill(2)
    return None


def resolve_fiscal_year(conn, purchase_date: str | None) -> dict | None:
    purchase_date_sql = parse_ledger_date_for_sql(purchase_date)
    if not purchase_date_sql:
        return None

    row = conn.execute(
        """
        SELECT *
        FROM finance_fiscal_years
        WHERE date(?) BETWEEN date(start_date) AND date(end_date)
        ORDER BY year_number DESC
        LIMIT 1
        """,
        (purchase_date_sql,),
    ).fetchone()
    return dict(row) if row else None


def _positive(value: Any) -> Decimal:
    amount = parse_money(value)
    return amount if amount > 0 else Decimal("0.00")


def _po_totals(rows) -> dict[str, Decimal]:
    """Calculate PO totals from eFinance accounting events.

    T/C 17 establishes the original encumbrance.
    T/C 18 represents encumbrance changes/change orders.
    T/C 20/21/22 represent payments/expenditures.

    AP rows frequently include negative encumbrance releases. Those releases are
    not displayed as the authorized encumbrance. Remaining is calculated from the
    authorized PO amount less paid activity and is never allowed to go negative.
    """
    original = Decimal("0.00")
    changes = Decimal("0.00")
    paid = Decimal("0.00")

    for row in rows:
        tc = row["transaction_code"]
        if tc == "17":
            original += _positive(row["encumbrance_amount"])
        elif tc == "18":
            changes += parse_money(row["encumbrance_amount"])
        elif tc in ENCUMBRANCE_TC and tc not in EXPENDITURE_TC:
            original += _positive(row["encumbrance_amount"])

        if tc in EXPENDITURE_TC:
            paid += parse_money(row["expenditure_amount"])

    authorized = original + changes
    if authorized < 0:
        authorized = Decimal("0.00")

    open_encumbrance = authorized - paid
    if open_encumbrance < 0:
        open_encumbrance = Decimal("0.00")

    return {
        "original": original,
        "changes": changes,
        "authorized": authorized,
        "paid": paid,
        "open_encumbrance": open_encumbrance,
    }


def _open_encumbrance_for_account(rows) -> Decimal:
    po_groups: dict[str, list] = {}
    non_po_open = Decimal("0.00")

    for row in rows:
        po_key = normalize_po(row["po_number"])
        if po_key:
            po_groups.setdefault(po_key, []).append(row)
        elif row["transaction_code"] in ENCUMBRANCE_TC:
            non_po_open += _positive(row["encumbrance_amount"])

    open_total = non_po_open
    for group_rows in po_groups.values():
        open_total += _po_totals(group_rows)["open_encumbrance"]
    return open_total


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
        if ledger.get("account_title") and not row["account_title"]:
            conn.execute(
                "UPDATE finance_budget_accounts SET account_title = ?, updated_at = ? WHERE id = ?",
                (ledger.get("account_title"), now, budget_account_id),
            )

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

    open_encumbrance = _open_encumbrance_for_account(rows)
    current_budget = original_budget + adjustments + transfers
    available = current_budget - spent - open_encumbrance
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE finance_budget_accounts
        SET original_budget = ?, budget_adjustments = ?, budget_transfers = ?,
            current_budget = ?, spent_amount = ?, encumbered_amount = ?,
            available_amount = ?, updated_at = ?
        WHERE id = ?
        """,
        (money(original_budget), money(adjustments), money(transfers), money(current_budget), money(spent), money(open_encumbrance), money(available), now, budget_account_id),
    )


def upsert_purchase_order(conn, *, ledger: dict) -> int | None:
    po_base = normalize_po(ledger.get("po_number"))
    if not po_base:
        return None

    now = utc_now_iso()
    row = conn.execute(
        """
        SELECT * FROM finance_purchase_orders
        WHERE department_name = ?
          AND COALESCE(fiscal_year_code, '') = COALESCE(?, '')
          AND normalized_po_number = ?
        """,
        (ledger["department_name"], ledger.get("fiscal_year_code"), po_base),
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
                po_base, po_base, ledger.get("vendor_id"), ledger.get("vendor_name"),
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

    totals = _po_totals(rows)
    status = "open" if totals["open_encumbrance"] > 0 else "closed"
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE finance_purchase_orders
        SET original_encumbrance = ?, encumbrance_changes = ?, current_encumbrance = ?,
            paid_amount = ?, remaining_encumbrance = ?, status = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            money(totals["original"]),
            money(totals["changes"]),
            money(totals["authorized"]),
            money(totals["paid"]),
            money(totals["open_encumbrance"]),
            status,
            now,
            purchase_order_id,
        ),
    )


def find_record_match(conn, *, ledger: dict) -> tuple[int | None, int, str | None]:
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
            return row["id"], 100, "Exact base PO match"

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

    po_numbers = sorted({normalize_po(row["po_number"]) for row in rows if row["po_number"]})
    budget_accounts = sorted({"/".join(filter(None, [row["fund"], row["budget_unit"], row["account_code"]])) for row in rows if row["account_code"]})
    vendor_id = next((row["vendor_id"] for row in rows if row["vendor_id"]), None)
    vendor_name = next((row["vendor_name"] for row in rows if row["vendor_name"]), None)

    budget_amount = sum((parse_money(row["budget_amount"]) for row in rows), Decimal("0.00"))
    paid = sum((parse_money(row["expenditure_amount"]) for row in rows if row["transaction_code"] in EXPENDITURE_TC), Decimal("0.00"))
    remaining = Decimal("0.00")
    po_groups: dict[str, list] = {}
    for row in rows:
        po_key = normalize_po(row["po_number"])
        if po_key:
            po_groups.setdefault(po_key, []).append(row)
    for group_rows in po_groups.values():
        remaining += _po_totals(group_rows)["open_encumbrance"]
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
        (record_id, rows[0]["fiscal_year_id"], fiscal_year_code, vendor_id, vendor_name, len(po_numbers), ", ".join([p for p in po_numbers if p]), ", ".join(budget_accounts), money(budget_amount), money(remaining), money(paid), money(remaining), now),
    )


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
