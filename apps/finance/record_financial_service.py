from __future__ import annotations

from decimal import Decimal
from typing import Any

from .db import get_connection
from .ledger_service import ensure_finance_ledger_schema, money, parse_money


def get_record_financial_history(record_id: int) -> dict[str, Any]:
    """Return fiscal-year ledger summaries for a Finance Record."""
    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM finance_record_fiscal_year_summary
            WHERE finance_record_id = ?
            ORDER BY fiscal_year_code
            """,
            (record_id,),
        ).fetchall()

    summaries = [dict(row) for row in rows]
    lifetime_paid = Decimal("0.00")
    lifetime_encumbered = Decimal("0.00")
    lifetime_remaining = Decimal("0.00")

    for row in summaries:
        lifetime_paid += parse_money(row.get("paid_amount"))
        lifetime_encumbered += parse_money(row.get("encumbered_amount"))
        lifetime_remaining += parse_money(row.get("remaining_encumbrance"))

    average_annual_paid = Decimal("0.00")
    if summaries:
        average_annual_paid = lifetime_paid / Decimal(len(summaries))

    return {
        "rows": summaries,
        "row_count": len(summaries),
        "lifetime_paid": money(lifetime_paid),
        "lifetime_encumbered": money(lifetime_encumbered),
        "lifetime_remaining": money(lifetime_remaining),
        "average_annual_paid": money(average_annual_paid),
    }
