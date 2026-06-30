from __future__ import annotations

from flask import abort, render_template, request, session

from modules.core.auth.decorators import login_required

from .access_service import can_access_department, can_manage_department, has_budget_view
from .blueprint import bp
from .ledger_query_service import (
    get_budget_account_detail,
    get_ledger_transaction_detail,
    get_purchase_order_detail,
    list_budget_accounts,
    list_ledger_transactions,
    list_purchase_orders,
)


@bp.route("/<department_name>/ledger")
@login_required
def ledger(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    if not can_access_department(user_id, department_name):
        abort(403)

    ledger_page = list_ledger_transactions(
        department_name=department_name,
        fiscal_year_code=(request.args.get("fiscal_year_code") or "").strip() or None,
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
        selected_fiscal_year_code=(request.args.get("fiscal_year_code") or "").strip(),
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
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    ledger_transaction = get_ledger_transaction_detail(ledger_transaction_id)
    if not ledger_transaction:
        abort(404)
    if not can_access_department(user_id, ledger_transaction["department_name"]):
        abort(403)

    return render_template(
        "finance/ledger_detail.html",
        department_name=ledger_transaction["department_name"],
        active_tab="ledger",
        ledger_transaction=ledger_transaction,
        can_manage=can_manage_department(user_id, ledger_transaction["department_name"]),
        can_view_budget=has_budget_view(user_id),
    )


@bp.route("/<department_name>/purchase-orders")
@login_required
def purchase_orders(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    if not can_access_department(user_id, department_name):
        abort(403)

    po_page = list_purchase_orders(
        department_name=department_name,
        fiscal_year_code=(request.args.get("fiscal_year_code") or "").strip() or None,
        status=(request.args.get("status") or "").strip() or None,
        vendor_q=(request.args.get("vendor_q") or "").strip() or None,
        q=(request.args.get("q") or "").strip() or None,
        page=request.args.get("page", default=1, type=int),
        per_page=100,
    )

    return render_template(
        "finance/purchase_orders.html",
        department_name=department_name,
        active_tab="purchase_orders",
        po_page=po_page,
        purchase_orders=po_page["rows"],
        selected_fiscal_year_code=(request.args.get("fiscal_year_code") or "").strip(),
        selected_status=(request.args.get("status") or "").strip(),
        vendor_q=(request.args.get("vendor_q") or "").strip(),
        q=(request.args.get("q") or "").strip(),
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=has_budget_view(user_id),
    )


@bp.route("/purchase-orders/<int:purchase_order_id>")
@login_required
def purchase_order_detail(purchase_order_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    purchase_order = get_purchase_order_detail(purchase_order_id)
    if not purchase_order:
        abort(404)
    if not can_access_department(user_id, purchase_order["department_name"]):
        abort(403)

    return render_template(
        "finance/purchase_order_detail.html",
        department_name=purchase_order["department_name"],
        active_tab="purchase_orders",
        purchase_order=purchase_order,
        can_manage=can_manage_department(user_id, purchase_order["department_name"]),
        can_view_budget=has_budget_view(user_id),
    )


@bp.route("/<department_name>/budget-accounts")
@login_required
def budget_accounts(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    if not can_access_department(user_id, department_name):
        abort(403)
    if not has_budget_view(user_id):
        abort(403)

    account_page = list_budget_accounts(
        department_name=department_name,
        fiscal_year_code=(request.args.get("fiscal_year_code") or "").strip() or None,
        q=(request.args.get("q") or "").strip() or None,
        page=request.args.get("page", default=1, type=int),
        per_page=100,
    )

    return render_template(
        "finance/budget_accounts.html",
        department_name=department_name,
        active_tab="budget_accounts",
        account_page=account_page,
        budget_accounts=account_page["rows"],
        selected_fiscal_year_code=(request.args.get("fiscal_year_code") or "").strip(),
        q=(request.args.get("q") or "").strip(),
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=True,
    )


@bp.route("/budget-accounts/<int:budget_account_id>")
@login_required
def budget_account_detail(budget_account_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    if not has_budget_view(user_id):
        abort(403)

    budget_account = get_budget_account_detail(budget_account_id)
    if not budget_account:
        abort(404)
    if not can_access_department(user_id, budget_account["department_name"]):
        abort(403)

    return render_template(
        "finance/budget_account_detail.html",
        department_name=budget_account["department_name"],
        active_tab="budget_accounts",
        budget_account=budget_account,
        can_manage=can_manage_department(user_id, budget_account["department_name"]),
        can_view_budget=True,
    )
