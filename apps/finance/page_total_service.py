from __future__ import annotations

from typing import Any

from .db import get_connection
from .ledger_service import ensure_finance_ledger_schema, normalize_text, parse_money


def purchase_order_totals(
    *,
    department_name: str,
    fiscal_year_code: str | None = None,
    status: str | None = None,
    vendor_q: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    where = ["po.department_name = ?"]
    params: list[Any] = [normalize_text(department_name)]

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
        row = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CAST(po.current_encumbrance AS REAL)), 0) AS encumbered,
                COALESCE(SUM(CAST(po.paid_amount AS REAL)), 0) AS paid,
                COALESCE(SUM(CAST(po.remaining_encumbrance AS REAL)), 0) AS remaining,
                SUM(CASE WHEN po.status = 'open' THEN 1 ELSE 0 END) AS open_count
            FROM finance_purchase_orders po
            LEFT JOIN finance_records r ON r.id = po.linked_record_id
            WHERE {where_sql}
            """,
            params,
        ).fetchone()

    return {
        "encumbered": parse_money(row["encumbered"]),
        "paid": parse_money(row["paid"]),
        "remaining": parse_money(row["remaining"]),
        "open_count": row["open_count"] or 0,
    }


def budget_account_totals(
    *,
    department_name: str,
    fiscal_year_code: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    where = ["ba.department_name = ?"]
    params: list[Any] = [normalize_text(department_name)]

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
        row = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CAST(ba.current_budget AS REAL)), 0) AS current_budget,
                COALESCE(SUM(CAST(ba.spent_amount AS REAL)), 0) AS spent,
                COALESCE(SUM(CAST(ba.encumbered_amount AS REAL)), 0) AS encumbered,
                COALESCE(SUM(CAST(ba.available_amount AS REAL)), 0) AS available
            FROM finance_budget_accounts ba
            WHERE {where_sql}
            """,
            params,
        ).fetchone()

    return {
        "current_budget": parse_money(row["current_budget"]),
        "spent": parse_money(row["spent"]),
        "encumbered": parse_money(row["encumbered"]),
        "available": parse_money(row["available"]),
    }
