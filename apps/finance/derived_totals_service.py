from __future__ import annotations

from typing import Any

from .db import get_connection
from .ledger_accounting_service import (
    recalculate_budget_account,
    recalculate_purchase_order,
    refresh_record_fiscal_year_summary,
)
from .ledger_record_service import update_record_financials_from_ledger
from .ledger_service import ensure_finance_ledger_schema, normalize_text


def rebuild_department_totals(
    *,
    department_name: str,
    fiscal_year_code: str | None = None,
    changed_by_user_id: int | None = None,
) -> dict[str, Any]:
    department_name = normalize_text(department_name)
    fiscal_year_code = normalize_text(fiscal_year_code)
    if not department_name:
        raise ValueError("department_name is required")

    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)

        if fiscal_year_code:
            budget_rows = conn.execute(
                """
                SELECT id
                FROM finance_budget_accounts
                WHERE department_name = ? AND fiscal_year_code = ?
                ORDER BY id
                """,
                (department_name, fiscal_year_code),
            ).fetchall()
            po_rows = conn.execute(
                """
                SELECT id
                FROM finance_purchase_orders
                WHERE department_name = ? AND fiscal_year_code = ?
                ORDER BY id
                """,
                (department_name, fiscal_year_code),
            ).fetchall()
            record_rows = conn.execute(
                """
                SELECT DISTINCT linked_record_id AS id
                FROM finance_ledger_transactions
                WHERE department_name = ?
                  AND fiscal_year_code = ?
                  AND linked_record_id IS NOT NULL
                ORDER BY linked_record_id
                """,
                (department_name, fiscal_year_code),
            ).fetchall()
            record_fy_rows = conn.execute(
                """
                SELECT DISTINCT linked_record_id AS id, fiscal_year_code
                FROM finance_ledger_transactions
                WHERE department_name = ?
                  AND fiscal_year_code = ?
                  AND linked_record_id IS NOT NULL
                ORDER BY linked_record_id, fiscal_year_code
                """,
                (department_name, fiscal_year_code),
            ).fetchall()
        else:
            budget_rows = conn.execute(
                """
                SELECT id
                FROM finance_budget_accounts
                WHERE department_name = ?
                ORDER BY id
                """,
                (department_name,),
            ).fetchall()
            po_rows = conn.execute(
                """
                SELECT id
                FROM finance_purchase_orders
                WHERE department_name = ?
                ORDER BY id
                """,
                (department_name,),
            ).fetchall()
            record_rows = conn.execute(
                """
                SELECT DISTINCT linked_record_id AS id
                FROM finance_ledger_transactions
                WHERE department_name = ?
                  AND linked_record_id IS NOT NULL
                ORDER BY linked_record_id
                """,
                (department_name,),
            ).fetchall()
            record_fy_rows = conn.execute(
                """
                SELECT DISTINCT linked_record_id AS id, fiscal_year_code
                FROM finance_ledger_transactions
                WHERE department_name = ?
                  AND linked_record_id IS NOT NULL
                  AND fiscal_year_code IS NOT NULL
                ORDER BY linked_record_id, fiscal_year_code
                """,
                (department_name,),
            ).fetchall()

        for row in budget_rows:
            recalculate_budget_account(conn, row["id"])

        for row in po_rows:
            recalculate_purchase_order(conn, row["id"])

        for row in record_rows:
            update_record_financials_from_ledger(
                conn,
                record_id=row["id"],
                changed_by_user_id=changed_by_user_id,
            )

        for row in record_fy_rows:
            refresh_record_fiscal_year_summary(conn, row["id"], row["fiscal_year_code"])

        conn.commit()

    return {
        "budget_accounts_refreshed": len(budget_rows),
        "purchase_orders_refreshed": len(po_rows),
        "records_refreshed": len(record_rows),
        "record_years_refreshed": len(record_fy_rows),
    }
