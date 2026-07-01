from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, session, url_for

from modules.core.auth.decorators import login_required

from .access_service import can_access_department, can_manage_department, has_budget_view
from .blueprint import bp
from .ledger_budget_overview_service import get_ledger_budget_page_context
from .service import save_budget_target_for_department


def _current_user_id():
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    return user_id


@bp.route("/<department_name>/budget-loading")
@login_required
def budget_loading(department_name: str):
    user_id = _current_user_id()
    if not can_access_department(user_id, department_name):
        abort(403)
    if not has_budget_view(user_id):
        abort(403)

    return render_template(
        "finance/budget_loading.html",
        department_name=department_name,
        active_tab="budget",
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=True,
    )


@bp.route("/<department_name>/budget", methods=["GET", "POST"])
@login_required
def budget(department_name: str):
    user_id = _current_user_id()
    if not can_access_department(user_id, department_name):
        abort(403)
    if not has_budget_view(user_id):
        abort(403)

    if request.method == "POST":
        if not can_manage_department(user_id, department_name):
            abort(403)

        fiscal_year = request.form.get("fiscal_year", type=int)
        total_budget = (request.form.get("total_budget") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            save_budget_target_for_department(
                department_name=department_name,
                fiscal_year=fiscal_year,
                total_budget=total_budget,
                notes=notes,
                changed_by_user_id=user_id,
            )
            flash("Budget settings saved successfully.", "success")
        except Exception as exc:
            flash(f"Budget settings could not be saved: {exc}", "error")

        return redirect(url_for("finance.budget", department_name=department_name, year=fiscal_year))

    selected_year = request.args.get("year", type=int)
    budget_context = get_ledger_budget_page_context(
        department_name=department_name,
        year=selected_year,
    )

    return render_template(
        "finance/budget.html",
        department_name=department_name,
        active_tab="budget",
        selected_year=budget_context["selected_year"],
        year_options=budget_context["year_options"],
        budget_summary=budget_context["summary"],
        budget_dashboard=budget_context["dashboard"],
        budget_breakdown=budget_context["breakdown"],
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=True,
    )
