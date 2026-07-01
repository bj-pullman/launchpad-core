from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, session, url_for

from modules.core.auth.decorators import login_required

from .access_service import can_access_department, can_manage_department, has_budget_view
from .blueprint import bp
from .derived_totals_service import rebuild_department_totals
from .fiscal_year_service import list_fiscal_years
from .ledger_budget_overview_service import get_ledger_budget_page_context
from .ledger_import_service import execute_ledger_import
from .ledger_query_service import (
    get_budget_account_detail,
    get_ledger_transaction_detail,
    get_purchase_order_detail,
    list_budget_accounts,
    list_ledger_transactions,
    list_purchase_orders,
)
from .ledger_validation_service import validate_ledger_import
from .page_total_service import budget_account_totals, purchase_order_totals
from .service import get_import_run_by_id, save_budget_target_for_department


def _current_user_id():
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    return user_id


def _is_import_validate_request() -> bool:
    return request.path.endswith("/validate") and "/imports/runs/" in request.path


def _selected_fiscal_year_code() -> str:
    return (request.args.get("fiscal_year_code") or "").strip()


def _fiscal_year_options() -> list[dict]:
    return list_fiscal_years(include_closed=True)


def _selected_group_by() -> str:
    group_by = (request.args.get("group_by") or "category").strip().lower()
    return group_by if group_by in {"category", "vendor", "month", "record_type", "status"} else "category"


@bp.before_request
def intercept_budget_overview_routes():
    if request.endpoint not in {"finance.budget", "finance.budget_loading"}:
        return None

    department_name = (request.view_args or {}).get("department_name")
    if not department_name:
        return None

    user_id = _current_user_id()
    if not can_access_department(user_id, department_name):
        abort(403)
    if not has_budget_view(user_id):
        abort(403)

    can_manage = can_manage_department(user_id, department_name)

    if request.method == "POST":
        if not can_manage:
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
                created_by_user_id=user_id,
            )
            flash("Budget Overview settings saved successfully.", "success")
        except Exception as exc:
            flash(f"Budget Overview settings failed: {exc}", "error")

        return redirect(url_for("finance.budget", department_name=department_name, year=fiscal_year))

    if request.endpoint == "finance.budget_loading":
        return render_template(
            "finance/budget_loading.html",
            department_name=department_name,
            active_tab="budget",
            can_view_budget=True,
            can_manage=can_manage,
        )

    try:
        rebuild_department_totals(
            department_name=department_name,
            changed_by_user_id=user_id,
        )
    except Exception as exc:
        flash(f"Budget totals refresh failed: {exc}", "error")

    selected_year = request.args.get("year", type=int)
    selected_group_by = _selected_group_by()
    budget_context = get_ledger_budget_page_context(
        department_name=department_name,
        year=selected_year,
    )
    budget_dashboard = budget_context["dashboard"]

    return render_template(
        "finance/budget.html",
        department_name=department_name,
        active_tab="budget",
        can_manage=can_manage,
        can_view_budget=True,
        year_options=budget_context["year_options"],
        selected_year=budget_context["selected_year"],
        selected_group_by=selected_group_by,
        selected_q=(request.args.get("q") or "").strip(),
        budget_summary=budget_context["summary"],
        budget_breakdown=budget_dashboard[selected_group_by],
        budget_dashboard=budget_dashboard,
    )


@bp.before_request
def intercept_ledger_import_validation_and_execution():
    if not _is_import_validate_request():
        return None

    view_args = request.view_args or {}
    department_name = view_args.get("department_name")
    run_id = view_args.get("run_id")
    if not department_name or not run_id:
        return None

    run = get_import_run_by_id(run_id)
    if not run or run.get("import_type") != "transactions":
        return None

    user_id = _current_user_id()
    if not can_access_department(user_id, department_name):
        abort(403)

    if request.method == "GET":
        profile_id = run.get("profile_id")
        if not profile_id:
            flash("Complete mapping before validation.", "error")
            return redirect(url_for("finance.imports_mapping", department_name=department_name, run_id=run_id))

        validation = validate_ledger_import(
            run_id=run_id,
            profile_id=profile_id,
            default_department_name=department_name,
            preview_limit=20,
        )
        return render_template(
            "finance/imports_validate.html",
            department_name=department_name,
            active_tab="overview",
            import_tab="upload",
            run=run,
            validation=validation,
            can_manage=can_manage_department(user_id, department_name),
        )

    if request.method != "POST":
        return None

    if not can_manage_department(user_id, department_name):
        abort(403)

    try:
        result = execute_ledger_import(
            run_id=run_id,
            profile_id=run.get("profile_id"),
            default_department_name=department_name,
            created_by_user_id=user_id,
        )
        flash(
            f"Ledger import finished. Inserted {result['inserted_rows']} ledger row(s), "
            f"linked {result['linked_rows']} row(s) to records, "
            f"updated {result['budget_accounts_updated']} budget account(s), "
            f"updated {result['purchase_orders_updated']} purchase order(s), "
            f"skipped {result['skipped_rows']}, errors {result['error_rows']}.",
            "success",
        )
        return redirect(url_for("finance.ledger", department_name=department_name))
    except Exception as exc:
        flash(f"Ledger import execution failed: {exc}", "error")
        return redirect(url_for("finance.imports_validate", department_name=department_name, run_id=run_id))


@bp.route("/<department_name>/ledger")
@login_required
def ledger(department_name: str):
    user_id = _current_user_id()
    if not can_access_department(user_id, department_name):
        abort(403)

    selected_fiscal_year_code = _selected_fiscal_year_code()
    ledger_page = list_ledger_transactions(
        department_name=department_name,
        fiscal_year_code=selected_fiscal_year_code or None,
        archive_status=(request.args.get("archive_status") or "active").strip(),
        ledger_kind=(request.args.get("ledger_kind") or "").strip() or None,
        review_status=(request.args.get("review_status") or "").strip() or None,
        transaction_code=(request.args.get("transaction_code") or "").strip() or None,
        vendor_q=(request.args.get("vendor_q") or "").strip() or None,
        po_number=(request.args.get("po_number") or "").strip() or None,
        q=(request.args.get("q") or "").strip() or None,
        page=request.args.get("page", default=1, type=int),
        per_page=100,
    )

    return render_template(
        "finance/ledger.html",
        department_name=department_name,
        active_tab="ledger",
        ledger_page=ledger_page,
        ledgers=ledger_page["rows"],
        fiscal_years=_fiscal_year_options(),
        selected_fiscal_year_code=selected_fiscal_year_code,
        selected_archive_status=(request.args.get("archive_status") or "active").strip(),
        selected_ledger_kind=(request.args.get("ledger_kind") or "").strip(),
        selected_review_status=(request.args.get("review_status") or "").strip(),
        selected_transaction_code=(request.args.get("transaction_code") or "").strip(),
        vendor_q=(request.args.get("vendor_q") or "").strip(),
        po_number=(request.args.get("po_number") or "").strip(),
        q=(request.args.get("q") or "").strip(),
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=has_budget_view(user_id),
    )


@bp.route("/ledger/<int:ledger_transaction_id>")
@login_required
def ledger_detail(ledger_transaction_id: int):
    user_id = _current_user_id()
    ledger_transaction = get_ledger_transaction_detail(ledger_transaction_id)
    if not ledger_transaction:
        abort(404)
    department_name = ledger_transaction["department_name"]
    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/ledger_detail.html",
        department_name=department_name,
        active_tab="ledger",
        ledger_transaction=ledger_transaction,
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=has_budget_view(user_id),
    )


@bp.route("/<department_name>/purchase-orders")
@login_required
def purchase_orders(department_name: str):
    user_id = _current_user_id()
    if not can_access_department(user_id, department_name):
        abort(403)

    selected_fiscal_year_code = _selected_fiscal_year_code()
    selected_status = (request.args.get("status") or "").strip()
    vendor_q = (request.args.get("vendor_q") or "").strip()
    q = (request.args.get("q") or "").strip()
    po_page = list_purchase_orders(
        department_name=department_name,
        fiscal_year_code=selected_fiscal_year_code or None,
        status=selected_status or None,
        vendor_q=vendor_q or None,
        q=q or None,
        page=request.args.get("page", default=1, type=int),
        per_page=100,
    )
    po_summary = purchase_order_totals(
        department_name=department_name,
        fiscal_year_code=selected_fiscal_year_code or None,
        status=selected_status or None,
        vendor_q=vendor_q or None,
        q=q or None,
    )

    return render_template(
        "finance/purchase_orders.html",
        department_name=department_name,
        active_tab="purchase_orders",
        po_page=po_page,
        po_summary=po_summary,
        purchase_orders=po_page["rows"],
        fiscal_years=_fiscal_year_options(),
        selected_fiscal_year_code=selected_fiscal_year_code,
        selected_status=selected_status,
        vendor_q=vendor_q,
        q=q,
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=has_budget_view(user_id),
    )


@bp.route("/purchase-orders/<int:purchase_order_id>")
@login_required
def purchase_order_detail(purchase_order_id: int):
    user_id = _current_user_id()
    purchase_order = get_purchase_order_detail(purchase_order_id)
    if not purchase_order:
        abort(404)
    department_name = purchase_order["department_name"]
    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/purchase_order_detail.html",
        department_name=department_name,
        active_tab="purchase_orders",
        purchase_order=purchase_order,
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=has_budget_view(user_id),
    )


@bp.route("/<department_name>/budget-accounts")
@login_required
def budget_accounts(department_name: str):
    user_id = _current_user_id()
    if not can_access_department(user_id, department_name):
        abort(403)
    if not has_budget_view(user_id):
        abort(403)

    selected_fiscal_year_code = _selected_fiscal_year_code()
    q = (request.args.get("q") or "").strip()
    account_page = list_budget_accounts(
        department_name=department_name,
        fiscal_year_code=selected_fiscal_year_code or None,
        q=q or None,
        page=request.args.get("page", default=1, type=int),
        per_page=100,
    )
    account_summary = budget_account_totals(
        department_name=department_name,
        fiscal_year_code=selected_fiscal_year_code or None,
        q=q or None,
    )

    return render_template(
        "finance/budget_accounts.html",
        department_name=department_name,
        active_tab="budget_accounts",
        account_page=account_page,
        account_summary=account_summary,
        budget_accounts=account_page["rows"],
        fiscal_years=_fiscal_year_options(),
        selected_fiscal_year_code=selected_fiscal_year_code,
        q=q,
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=True,
    )


@bp.route("/budget-accounts/<int:budget_account_id>")
@login_required
def budget_account_detail(budget_account_id: int):
    user_id = _current_user_id()
    if not has_budget_view(user_id):
        abort(403)

    budget_account = get_budget_account_detail(budget_account_id)
    if not budget_account:
        abort(404)
    department_name = budget_account["department_name"]
    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/budget_account_detail.html",
        department_name=department_name,
        active_tab="budget_accounts",
        budget_account=budget_account,
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=True,
    )
