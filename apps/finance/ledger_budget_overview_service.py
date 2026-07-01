from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from .db import get_connection
from .ledger_service import ensure_finance_ledger_schema, money, parse_money
from .service import get_budget_target_for_department


def _money_sum(rows: list[dict[str, Any]], key: str) -> Decimal:
    return sum((parse_money(row.get(key)) for row in rows), Decimal("0.00"))


def _empty_breakdown(group_by: str) -> dict[str, Any]:
    return {
        "rows": [],
        "chart_labels": [],
        "chart_values": [],
        "top_bucket": None,
        "group_by": group_by,
    }


def _build_breakdown(rows: list[dict[str, Any]], *, group_by: str) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "label": "",
            "total_spent": Decimal("0.00"),
            "record_count": 0,
        }
    )

    for row in rows:
        if group_by == "vendor":
            label = row.get("vendor_name") or "Unassigned Vendor"
        elif group_by == "month":
            purchase_date = row.get("purchase_date") or ""
            label = purchase_date[:7] if len(purchase_date) >= 7 else "No Date"
        elif group_by == "record_type":
            label = (row.get("record_type") or "Unassigned Type").replace("_", " ").title()
        elif group_by == "status":
            label = (row.get("record_status") or row.get("po_status") or "Unassigned Status").replace("_", " ").title()
        else:
            label = row.get("account_title") or row.get("account_code") or "Unassigned Account"

        bucket = buckets[label]
        bucket["label"] = label
        bucket["total_spent"] += parse_money(row.get("expenditure_amount"))
        bucket["record_count"] += 1

    total_spent = sum((item["total_spent"] for item in buckets.values()), Decimal("0.00"))
    results = []
    for item in sorted(buckets.values(), key=lambda item: (item["total_spent"], item["label"]), reverse=True):
        average_spend = item["total_spent"] / item["record_count"] if item["record_count"] else Decimal("0.00")
        percent = (item["total_spent"] / total_spent * Decimal("100")) if total_spent else Decimal("0.00")
        results.append(
            {
                "label": item["label"],
                "total_spent": item["total_spent"],
                "record_count": item["record_count"],
                "average_spend": average_spend,
                "percent_of_total": percent,
            }
        )

    return {
        "rows": results,
        "chart_labels": [item["label"] for item in results],
        "chart_values": [float(item["total_spent"]) for item in results],
        "top_bucket": results[0] if results else None,
        "group_by": group_by,
    }


def get_ledger_budget_page_context(*, department_name: str, year: int | None = None) -> dict[str, Any]:
    with get_connection() as conn:
        ensure_finance_ledger_schema(conn)
        fiscal_years = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM finance_fiscal_years
                ORDER BY year_number DESC
                """
            ).fetchall()
        ]

        selected_fy = None
        if year:
            selected_fy = next((fy for fy in fiscal_years if int(fy["year_number"]) == int(year)), None)
        if not selected_fy:
            selected_fy = next((fy for fy in fiscal_years if fy.get("is_current")), None) or (fiscal_years[0] if fiscal_years else None)

        selected_year = int(selected_fy["year_number"]) if selected_fy else year
        selected_code = selected_fy.get("code") if selected_fy else None

        account_params: list[Any] = [department_name]
        account_where = ["department_name = ?"]
        if selected_code:
            account_where.append("fiscal_year_code = ?")
            account_params.append(selected_code)
        accounts = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT *
                FROM finance_budget_accounts
                WHERE {' AND '.join(account_where)}
                """,
                account_params,
            ).fetchall()
        ]

        ledger_params: list[Any] = [department_name]
        ledger_where = ["l.department_name = ?", "l.archive_status IN ('active', 'archived')"]
        if selected_code:
            ledger_where.append("l.fiscal_year_code = ?")
            ledger_params.append(selected_code)
        ledger_rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    l.*,
                    ba.account_title,
                    r.record_type,
                    r.status AS record_status,
                    po.status AS po_status
                FROM finance_ledger_transactions l
                LEFT JOIN finance_budget_accounts ba ON ba.id = l.budget_account_id
                LEFT JOIN finance_records r ON r.id = l.linked_record_id
                LEFT JOIN finance_purchase_orders po ON po.id = l.purchase_order_id
                WHERE {' AND '.join(ledger_where)}
                """,
                ledger_params,
            ).fetchall()
        ]

    total_budget = _money_sum(accounts, "current_budget")
    total_spent = _money_sum(accounts, "spent_amount")
    encumbrance_total = _money_sum(accounts, "encumbered_amount")
    remaining_budget = total_budget - total_spent - encumbrance_total
    record_ids = {row.get("linked_record_id") for row in ledger_rows if row.get("linked_record_id")}
    record_count = len(record_ids)
    average_spend = total_spent / Decimal(record_count) if record_count else Decimal("0.00")
    percent_used = Decimal("0.00")
    if total_budget > 0:
        percent_used = ((total_spent + encumbrance_total) / total_budget) * Decimal("100")
    elif total_spent or encumbrance_total:
        percent_used = Decimal("100.00")

    budget_target = get_budget_target_for_department(department_name, selected_year)
    if total_budget == 0 and budget_target.get("total_budget"):
        total_budget = budget_target["total_budget"]
        remaining_budget = total_budget - total_spent - encumbrance_total

    summary = {
        "total_budget": total_budget,
        "total_spent": total_spent,
        "remaining_budget": remaining_budget,
        "percent_used": percent_used.quantize(Decimal("0.1")),
        "record_count": record_count,
        "average_spend": average_spend,
        "renewals_total": Decimal("0.00"),
        "purchases_total": Decimal("0.00"),
        "active_total": total_spent,
        "encumbrance_total": encumbrance_total,
        "budget_target": budget_target,
    }

    dashboard = {
        "category": _build_breakdown(ledger_rows, group_by="category") if ledger_rows else _empty_breakdown("category"),
        "vendor": _build_breakdown(ledger_rows, group_by="vendor") if ledger_rows else _empty_breakdown("vendor"),
        "month": _build_breakdown(ledger_rows, group_by="month") if ledger_rows else _empty_breakdown("month"),
        "record_type": _build_breakdown(ledger_rows, group_by="record_type") if ledger_rows else _empty_breakdown("record_type"),
        "status": _build_breakdown(ledger_rows, group_by="status") if ledger_rows else _empty_breakdown("status"),
    }

    return {
        "selected_year": selected_year,
        "year_options": [int(fy["year_number"]) for fy in fiscal_years],
        "summary": summary,
        "dashboard": dashboard,
        "breakdown": dashboard["category"],
    }
