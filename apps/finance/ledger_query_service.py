from __future__ import annotations

from decimal import Decimal
from typing import Any

from .db import get_connection
from .ledger_accounting_service import normalize_po, po_line_item
from .ledger_service import ensure_finance_ledger_schema, money, normalize_text, parse_money


def _page_args(page: int = 1, per_page: int = 100) -> tuple[int, int, int]:
    page = max(int(page or 1), 1)
    per_page = max(min(int(per_page or 100), 250), 25)
    offset = (page - 1) * per_page
    return page, per_page, offset


def list_ledger_transactions(
    *,
    department_name: str,
    fiscal_year_code: str | None = None,
    archive_status: str = "active",
    ledger_kind: str | None = None,
    review_status: str | None = None,
    transaction_code: str | None = None,
    vendor_q: str | None = None,
    po_number: str | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    """Return a paged Ledger view for the Finance UI."""
    department_name = normalize_text(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    page, per_page, offset = _page_args(page, per_page)
    where = ["l.department_name = ?"]
    params: list[Any] = [department_name]

    archive_status = normalize_text(archive_status) or "active"
    if archive_status != "all":
        where.append("l.archive_status = ?")
        params.append(archive_status)

    filters = {
        "l.fiscal_year_code": fiscal_year_code,
        "l.ledger_kind": ledger_kind,
        "l.review_status": review_status,
        "l.transaction_code": transaction_code,
    }
    for column, value in filters.items():
        value = normalize_text(value)
        if value:
            where.append(f"{column} = ?")
            params.append(value)

    po_number = normalize_text(po_number)
    if po_number:
        where.append("LOWER(COALESCE(l.po_number, '')) LIKE LOWER(?)")
        params.append(f"%{po_number}%")

    vendor_q = normalize_text(vendor_q)
    if vendor_q:
        where.append(
            """
            (
                LOWER(COALESCE(l.vendor_name, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(l.vendor_code, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(v.vendor_name, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(v.friendly_name, '')) LIKE LOWER(?)
            )
            """
        )
        term = f"%{vendor_q}%"
        params.extend([term, term, term, term])

    q = normalize_text(q)
    if q:
        where.append(
            """
            (
                LOWER(COALESCE(l.title, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(l.description, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(l.fund, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(l.budget_unit, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(l.account_code, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(l.po_number, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(r.title, '')) LIKE LOWER(?)
            )
            """
        )
        term = f"%{q}%"
        params.extend([term] * 7)

    where_sql = " AND ".join(f"({item})" for item in where)

    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        total = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM finance_ledger_transactions l
            LEFT JOIN finance_vendors v ON v.id = l.vendor_id
            LEFT JOIN finance_records r ON r.id = l.linked_record_id
            WHERE {where_sql}
            """,
            params,
        ).fetchone()["count"]

        rows = conn.execute(
            f"""
            SELECT
                l.*,
                v.friendly_name AS vendor_friendly_name,
                v.vendor_name AS matched_vendor_name,
                r.title AS linked_record_title,
                po.status AS purchase_order_status,
                po.remaining_encumbrance AS po_remaining_encumbrance,
                ba.current_budget AS budget_current_budget,
                ba.available_amount AS budget_available_amount
            FROM finance_ledger_transactions l
            LEFT JOIN finance_vendors v ON v.id = l.vendor_id
            LEFT JOIN finance_records r ON r.id = l.linked_record_id
            LEFT JOIN finance_purchase_orders po ON po.id = l.purchase_order_id
            LEFT JOIN finance_budget_accounts ba ON ba.id = l.budget_account_id
            WHERE {where_sql}
            ORDER BY
                CASE WHEN l.purchase_date IS NULL OR l.purchase_date = '' THEN 1 ELSE 0 END,
                l.purchase_date DESC,
                l.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, per_page, offset],
        ).fetchall()

    total_pages = max((total + per_page - 1) // per_page, 1)
    return {
        "rows": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    }


def get_ledger_transaction_detail(transaction_id: int) -> dict | None:
    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        row = conn.execute(
            """
            SELECT
                l.*,
                v.friendly_name AS vendor_friendly_name,
                v.vendor_name AS matched_vendor_name,
                r.title AS linked_record_title,
                po.po_number AS purchase_order_number,
                ba.account_title AS budget_account_title,
                ba.current_budget AS budget_current_budget,
                ba.available_amount AS budget_available_amount
            FROM finance_ledger_transactions l
            LEFT JOIN finance_vendors v ON v.id = l.vendor_id
            LEFT JOIN finance_records r ON r.id = l.linked_record_id
            LEFT JOIN finance_purchase_orders po ON po.id = l.purchase_order_id
            LEFT JOIN finance_budget_accounts ba ON ba.id = l.budget_account_id
            WHERE l.id = ?
            """,
            (transaction_id,),
        ).fetchone()
    return dict(row) if row else None


def list_purchase_orders(
    *,
    department_name: str,
    fiscal_year_code: str | None = None,
    status: str | None = None,
    vendor_q: str | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    department_name = normalize_text(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    page, per_page, offset = _page_args(page, per_page)
    where = ["po.department_name = ?"]
    params: list[Any] = [department_name]

    for column, value in {
        "po.fiscal_year_code": fiscal_year_code,
        "po.status": status,
    }.items():
        value = normalize_text(value)
        if value:
            where.append(f"{column} = ?")
            params.append(value)

    vendor_q = normalize_text(vendor_q)
    if vendor_q:
        where.append("LOWER(COALESCE(po.vendor_name, '')) LIKE LOWER(?)")
        params.append(f"%{vendor_q}%")

    q = normalize_text(q)
    if q:
        where.append(
            """
            (
                LOWER(COALESCE(po.po_number, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(po.vendor_name, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(po.account_code, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(r.title, '')) LIKE LOWER(?)
            )
            """
        )
        term = f"%{q}%"
        params.extend([term] * 4)

    where_sql = " AND ".join(f"({item})" for item in where)

    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        total = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM finance_purchase_orders po
            LEFT JOIN finance_records r ON r.id = po.linked_record_id
            WHERE {where_sql}
            """,
            params,
        ).fetchone()["count"]

        rows = conn.execute(
            f"""
            SELECT
                po.*,
                r.title AS linked_record_title,
                ba.account_title AS budget_account_title
            FROM finance_purchase_orders po
            LEFT JOIN finance_records r ON r.id = po.linked_record_id
            LEFT JOIN finance_budget_accounts ba ON ba.id = po.budget_account_id
            WHERE {where_sql}
            ORDER BY po.fiscal_year_code DESC, po.po_number COLLATE NOCASE ASC
            LIMIT ? OFFSET ?
            """,
            [*params, per_page, offset],
        ).fetchall()

    total_pages = max((total + per_page - 1) // per_page, 1)
    return {
        "rows": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    }


def _build_po_line_items(activity: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in activity:
        raw_po = row.get("po_number")
        line_number = po_line_item(raw_po) or "base"
        item = grouped.setdefault(
            line_number,
            {
                "line_number": line_number,
                "po_number": raw_po,
                "description": row.get("description") or row.get("title"),
                "account_code": row.get("account_code"),
                "budget_unit": row.get("budget_unit"),
                "ledger_count": 0,
                "encumbered_amount": Decimal("0.00"),
                "paid_amount": Decimal("0.00"),
                "remaining_amount": Decimal("0.00"),
            },
        )
        item["ledger_count"] += 1
        if row.get("description") and not item.get("description"):
            item["description"] = row.get("description")
        item["encumbered_amount"] += parse_money(row.get("encumbrance_amount"))
        item["paid_amount"] += parse_money(row.get("expenditure_amount"))

    results = []
    for item in grouped.values():
        item["remaining_amount"] = item["encumbered_amount"]
        item["encumbered_amount"] = money(item["encumbered_amount"])
        item["paid_amount"] = money(item["paid_amount"])
        item["remaining_amount"] = money(item["remaining_amount"])
        results.append(item)

    return sorted(results, key=lambda item: (item["line_number"] == "base", item["line_number"]))


def get_purchase_order_detail(purchase_order_id: int) -> dict | None:
    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        po = conn.execute(
            """
            SELECT
                po.*,
                r.title AS linked_record_title,
                ba.account_title AS budget_account_title,
                ba.fund AS budget_fund,
                ba.budget_unit AS budget_unit_full,
                ba.current_budget AS budget_current_budget,
                ba.available_amount AS budget_available_amount
            FROM finance_purchase_orders po
            LEFT JOIN finance_records r ON r.id = po.linked_record_id
            LEFT JOIN finance_budget_accounts ba ON ba.id = po.budget_account_id
            WHERE po.id = ?
            """,
            (purchase_order_id,),
        ).fetchone()
        if not po:
            return None

        activity = conn.execute(
            """
            SELECT *
            FROM finance_ledger_transactions
            WHERE purchase_order_id = ?
            ORDER BY po_number COLLATE NOCASE ASC, purchase_date ASC, id ASC
            """,
            (purchase_order_id,),
        ).fetchall()

    activity_rows = [dict(row) for row in activity]
    result = dict(po)
    result["base_po_number"] = normalize_po(result.get("po_number")) or result.get("po_number")
    result["activity"] = activity_rows
    result["line_items"] = _build_po_line_items(activity_rows)
    result["line_item_count"] = len(result["line_items"])
    return result


def list_budget_accounts(
    *,
    department_name: str,
    fiscal_year_code: str | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    department_name = normalize_text(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    page, per_page, offset = _page_args(page, per_page)
    where = ["ba.department_name = ?"]
    params: list[Any] = [department_name]

    fiscal_year_code = normalize_text(fiscal_year_code)
    if fiscal_year_code:
        where.append("ba.fiscal_year_code = ?")
        params.append(fiscal_year_code)

    q = normalize_text(q)
    if q:
        where.append(
            """
            (
                LOWER(COALESCE(ba.fund, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(ba.budget_unit, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(ba.account_code, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(ba.account_title, '')) LIKE LOWER(?)
            )
            """
        )
        term = f"%{q}%"
        params.extend([term] * 4)

    where_sql = " AND ".join(f"({item})" for item in where)

    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        total = conn.execute(
            f"SELECT COUNT(*) AS count FROM finance_budget_accounts ba WHERE {where_sql}",
            params,
        ).fetchone()["count"]
        rows = conn.execute(
            f"""
            SELECT *
            FROM finance_budget_accounts ba
            WHERE {where_sql}
            ORDER BY ba.fiscal_year_code DESC, ba.fund, ba.budget_unit, ba.account_code
            LIMIT ? OFFSET ?
            """,
            [*params, per_page, offset],
        ).fetchall()

    total_pages = max((total + per_page - 1) // per_page, 1)
    return {
        "rows": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    }


def get_budget_account_detail(budget_account_id: int) -> dict | None:
    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        account = conn.execute(
            "SELECT * FROM finance_budget_accounts WHERE id = ?",
            (budget_account_id,),
        ).fetchone()
        if not account:
            return None
        activity = conn.execute(
            """
            SELECT *
            FROM finance_ledger_transactions
            WHERE budget_account_id = ?
            ORDER BY purchase_date ASC, id ASC
            """,
            (budget_account_id,),
        ).fetchall()
        purchase_orders = conn.execute(
            """
            SELECT *
            FROM finance_purchase_orders
            WHERE budget_account_id = ?
            ORDER BY po_number COLLATE NOCASE ASC
            """,
            (budget_account_id,),
        ).fetchall()

    result = dict(account)
    result["activity"] = [dict(row) for row in activity]
    result["purchase_orders"] = [dict(row) for row in purchase_orders]
    return result


def get_record_fiscal_year_history(record_id: int) -> list[dict]:
    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM finance_record_fiscal_year_summary
            WHERE finance_record_id = ?
            ORDER BY fiscal_year_code ASC
            """,
            (record_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_record_ledger_summary(record_id: int) -> dict:
    history = get_record_fiscal_year_history(record_id)
    total_paid = sum((parse_money(row.get("paid_amount")) for row in history), Decimal("0.00"))
    total_encumbered = sum((parse_money(row.get("encumbered_amount")) for row in history), Decimal("0.00"))
    return {
        "history": history,
        "total_paid": money(total_paid),
        "total_encumbered": money(total_encumbered),
        "year_count": len(history),
    }
