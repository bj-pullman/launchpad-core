from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .db import get_connection


def _money(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    cleaned = str(value).strip().replace("$", "").replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        return Decimal(cleaned or "0").quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def get_finance_setup_status(department_name: str | None = None) -> dict[str, Any]:
    department_name = (department_name or "").strip()

    with get_connection() as conn:
        fiscal_year_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM finance_fiscal_years
            WHERE department_name = ?
            """,
            (department_name,),
        ).fetchone()["count"]

        current_fy = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_years
            WHERE department_name = ?
              AND is_current = 1
            ORDER BY year_number DESC
            LIMIT 1
            """,
            (department_name,),
        ).fetchone()

    current = dict(current_fy) if current_fy else None
    budget_amount = _money(current.get("adopted_budget")) if current else Decimal("0.00")
    has_fiscal_year = fiscal_year_count > 0
    has_current_fiscal_year = current is not None
    has_budget_amount = budget_amount > 0

    missing_items = []
    if not has_fiscal_year:
        missing_items.append("Create at least one fiscal year.")
    if not has_current_fiscal_year:
        missing_items.append("Mark one fiscal year as Current.")
    if has_current_fiscal_year and not has_budget_amount:
        missing_items.append("Enter the Budget Amount for the current fiscal year.")

    return {
        "is_ready": has_fiscal_year and has_current_fiscal_year and has_budget_amount,
        "has_fiscal_year": has_fiscal_year,
        "has_current_fiscal_year": has_current_fiscal_year,
        "has_adopted_budget": has_budget_amount,
        "has_budget_amount": has_budget_amount,
        "current_fiscal_year": current,
        "adopted_budget": budget_amount,
        "budget_amount": budget_amount,
        "missing_items": missing_items,
    }


def require_finance_setup_ready() -> dict[str, Any]:
    status = get_finance_setup_status()
    if not status["is_ready"]:
        raise ValueError("Finance setup must be completed before adding, importing, or viewing operational data.")
    return status


def update_fiscal_year_adopted_budget(*, fiscal_year_id: int, adopted_budget: str | None) -> None:
    budget_amount = _money(adopted_budget)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_fiscal_years
            SET adopted_budget = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(budget_amount), fiscal_year_id),
        )
        conn.commit()
