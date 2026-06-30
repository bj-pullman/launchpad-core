from __future__ import annotations

from flask import abort, redirect, url_for, request, session

from modules.core.auth.decorators import login_required

from .access_service import can_access_department, has_budget_view
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

    list_ledger_transactions(
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
    return redirect(url_for("finance.transactions", department_name=department_name))


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
    return redirect(url_for("finance.transactions", department_name=ledger_transaction["department_name"]))


@bp.route("/<department_name>/purchase-orders")
@login_required
def purchase_orders(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    if not can_access_department(user_id, department_name):
        abort(403)
    list_purchase_orders(department_name=department_name, page=request.args.get("page", default=1, type=int), per_page=100)
    return redirect(url_for("finance.transactions", department_name=department_name))


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
    return redirect(url_for("finance.transactions", department_name=purchase_order["department_name"]))


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
    list_budget_accounts(department_name=department_name, page=request.args.get("page", default=1, type=int), per_page=100)
    return redirect(url_for("finance.budget_loading", department_name=department_name))


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
    return redirect(url_for("finance.budget_loading", department_name=budget_account["department_name"]))
