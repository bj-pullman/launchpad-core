from __future__ import annotations

from flask import abort, flash, redirect, request, session, url_for

from .access_service import can_access_department, can_manage_department
from .blueprint import bp
from .finance_setup_guard_service import get_finance_setup_status, update_fiscal_year_adopted_budget
from .fiscal_year_service import create_fiscal_year, update_fiscal_year_status


_ALLOWED_SETUP_ENDPOINTS = {
    "finance.index",
    "finance.department_overview",
    "finance.fiscal_years",
    "finance.fiscal_year_status_update",
    "finance.fiscal_year_checklist",
    "finance.fiscal_year_checklist_item_update",
}


def _department_name() -> str | None:
    view_args = request.view_args or {}
    return view_args.get("department_name") or request.form.get("department_name")


def _setup_redirect(department_name: str):
    flash("Complete Fiscal Year setup before adding, importing, or viewing operational Finance data.", "error")
    return redirect(
        url_for("finance.department_overview", department_name=department_name)
        + "?open_modal=finance-settings-modal&open_tab=start-year"
    )


@bp.app_context_processor
def inject_finance_setup_status():
    try:
        return {"finance_setup_status": get_finance_setup_status()}
    except Exception:
        return {"finance_setup_status": None}


@bp.before_request
def intercept_fiscal_year_create_with_budget():
    if request.endpoint != "finance.fiscal_years" or request.method != "POST":
        return None

    department_name = _department_name()
    user_id = session.get("user_id")
    if not user_id or not department_name:
        abort(403)
    if not can_access_department(user_id, department_name) or not can_manage_department(user_id, department_name):
        abort(403)

    year_number = request.form.get("year_number", type=int)
    start_date = (request.form.get("start_date") or "").strip()
    end_date = (request.form.get("end_date") or "").strip()
    friendly_name = (request.form.get("friendly_name") or "").strip()
    adopted_budget = (request.form.get("adopted_budget") or "").strip()
    fiscal_year_role = (request.form.get("fiscal_year_role") or "next").strip().lower()

    if fiscal_year_role not in {"previous", "current", "next"}:
        fiscal_year_role = "next"

    if not year_number or not start_date or not end_date or not adopted_budget:
        flash("Fiscal year, start date, end date, and adopted budget are required.", "error")
        return redirect(
            url_for("finance.department_overview", department_name=department_name)
            + "?open_modal=finance-settings-modal&open_tab=start-year"
        )

    try:
        fiscal_year_id = create_fiscal_year(
            year_number=year_number,
            start_date=start_date,
            end_date=end_date,
            friendly_name=friendly_name,
            make_current=fiscal_year_role == "current",
            make_next=fiscal_year_role == "next",
            created_by_user_id=user_id,
        )
        update_fiscal_year_adopted_budget(
            fiscal_year_id=fiscal_year_id,
            adopted_budget=adopted_budget,
        )

        if fiscal_year_role == "current":
            update_fiscal_year_status(
                fiscal_year_id=fiscal_year_id,
                status="active",
                is_current=True,
                is_next=False,
            )
        elif fiscal_year_role == "next":
            update_fiscal_year_status(
                fiscal_year_id=fiscal_year_id,
                status="planning",
                is_current=False,
                is_next=True,
            )
        else:
            update_fiscal_year_status(
                fiscal_year_id=fiscal_year_id,
                status="closed",
                is_current=False,
                is_next=False,
            )

        flash("Fiscal year created successfully.", "success")
        return redirect(
            url_for("finance.department_overview", department_name=department_name)
            + (
                "?open_modal=finance-settings-modal"
                "&open_tab=start-year"
                f"&open_panel=start-checklist-{fiscal_year_id}"
            )
        )
    except Exception as exc:
        flash(f"Fiscal year setup failed: {exc}", "error")
        return redirect(
            url_for("finance.department_overview", department_name=department_name)
            + "?open_modal=finance-settings-modal&open_tab=start-year"
        )


@bp.before_request
def require_fiscal_year_setup_for_finance_operations():
    if request.method in {"OPTIONS", "HEAD"}:
        return None
    if request.endpoint in _ALLOWED_SETUP_ENDPOINTS:
        return None
    if not request.endpoint or not request.endpoint.startswith("finance."):
        return None

    department_name = _department_name()
    if not department_name:
        return None

    status = get_finance_setup_status()
    if status["is_ready"]:
        return None

    return _setup_redirect(department_name)
