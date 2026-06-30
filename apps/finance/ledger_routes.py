from __future__ import annotations

from html import escape

from flask import abort, request, session

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

LT = chr(60)
GT = chr(62)


def _tag(name, body="", attrs=""):
    return f"{LT}{name}{attrs}{GT}{body}{LT}/{name}{GT}"


def _page(title, subtitle, body):
    style = "font-family:Verdana,Arial,sans-serif;margin:32px;color:#172033;"
    card = "border:1px solid #d9e2ef;border-radius:14px;padding:20px;margin-top:18px;background:#fff;"
    css = _tag("style", "table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #e5e7eb;padding:10px;text-align:left}th{background:#f8fafc}.muted{color:#64748b}.pill{display:inline-block;border:1px solid #cbd5e1;border-radius:999px;padding:2px 8px;font-size:12px}.metric{display:inline-block;margin:0 16px 16px 0;padding:12px 14px;border:1px solid #e5e7eb;border-radius:12px;background:#f8fafc}.metric strong{display:block;font-size:18px}.card{" + card + "}")
    head = _tag("head", _tag("title", escape(title)) + css)
    heading = _tag("h1", escape(title)) + _tag("p", escape(subtitle), " class='muted'")
    page_body = _tag("body", heading + _tag("div", body, " class='card'"), f" style='{style}'")
    return "<!doctype html>" + _tag("html", head + page_body)


def _money(value):
    return escape(str(value or "0.00"))


def _cell(value):
    return _tag("td", escape(str(value or "-")))


def _table(headers, rows):
    header_html = "".join(_tag("th", escape(item)) for item in headers)
    row_html = "".join(_tag("tr", "".join(_cell(value) for value in row)) for row in rows)
    return _tag("table", _tag("thead", _tag("tr", header_html)) + _tag("tbody", row_html))


def _empty(title, message):
    return _tag("h3", escape(title)) + _tag("p", escape(message), " class='muted'")


@bp.route("/<department_name>/ledger")
@login_required
def ledger(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    if not can_access_department(user_id, department_name):
        abort(403)

    page = list_ledger_transactions(
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
    rows = [
        [r.get("fiscal_year_code"), r.get("purchase_date"), r.get("transaction_code"), r.get("ledger_kind"), r.get("vendor_friendly_name") or r.get("vendor_name"), r.get("po_number"), r.get("account_code"), r.get("expenditure_amount"), r.get("encumbrance_amount"), r.get("linked_record_title") or "Unlinked"]
        for r in page["rows"]
    ]
    body = _tag("p", f"Showing {page['total']} ledger transaction(s).", " class='muted'")
    body += _table(["FY", "Date", "T/C", "Kind", "Vendor", "PO", "Account", "Paid", "Encumbered", "Record"], rows) if rows else _empty("No ledger transactions found", "Import an ERP Expenditure Audit Trail to populate the Ledger.")
    return _page(f"{department_name} Ledger", "ERP audit trail activity grouped by fiscal year, transaction code, purchase order, budget account, and linked record.", body)


@bp.route("/ledger/<int:ledger_transaction_id>")
@login_required
def ledger_detail(ledger_transaction_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    row = get_ledger_transaction_detail(ledger_transaction_id)
    if not row:
        abort(404)
    if not can_access_department(user_id, row["department_name"]):
        abort(403)
    body = _table(["Field", "Value"], [[key, value] for key, value in row.items()])
    return _page("Ledger Transaction", "Detailed ERP ledger row.", body)


@bp.route("/<department_name>/purchase-orders")
@login_required
def purchase_orders(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    if not can_access_department(user_id, department_name):
        abort(403)
    page = list_purchase_orders(department_name=department_name, page=request.args.get("page", default=1, type=int), per_page=100)
    rows = [[r.get("fiscal_year_code"), r.get("po_number"), r.get("vendor_name"), r.get("current_encumbrance"), r.get("paid_amount"), r.get("remaining_encumbrance"), r.get("linked_record_title") or "Unlinked", r.get("status")] for r in page["rows"]]
    body = _tag("p", f"Showing {page['total']} purchase order(s).", " class='muted'")
    body += _table(["FY", "PO", "Vendor", "Encumbered", "Paid", "Remaining", "Record", "Status"], rows) if rows else _empty("No purchase orders found", "Import ledger activity with PO numbers to build this page.")
    return _page(f"{department_name} Purchase Orders", "Purchase orders calculated from encumbrance and payment ledger activity.", body)


@bp.route("/purchase-orders/<int:purchase_order_id>")
@login_required
def purchase_order_detail(purchase_order_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    po = get_purchase_order_detail(purchase_order_id)
    if not po:
        abort(404)
    if not can_access_department(user_id, po["department_name"]):
        abort(403)
    body = _table(["Field", "Value"], [[key, value] for key, value in po.items() if key != "activity"])
    return _page(f"PO {po.get('po_number')}", "Purchase order rollup and ledger activity.", body)


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
    page = list_budget_accounts(department_name=department_name, page=request.args.get("page", default=1, type=int), per_page=100)
    totals = {"budget": 0.0, "spent": 0.0, "encumbered": 0.0, "available": 0.0}
    for r in page["rows"]:
        totals["budget"] += float(r.get("current_budget") or 0)
        totals["spent"] += float(r.get("spent_amount") or 0)
        totals["encumbered"] += float(r.get("encumbered_amount") or 0)
        totals["available"] += float(r.get("available_amount") or 0)
    metrics = "".join(_tag("span", _tag("strong", f"${value:,.2f}") + escape(label), " class='metric'") for label, value in [("Current Budget", totals["budget"]), ("Spent", totals["spent"]), ("Encumbered", totals["encumbered"]), ("Available", totals["available"])])
    rows = [[r.get("fiscal_year_code"), r.get("fund"), r.get("budget_unit"), r.get("account_code"), r.get("account_title"), r.get("current_budget"), r.get("spent_amount"), r.get("encumbered_amount"), r.get("available_amount")] for r in page["rows"]]
    body = metrics + _tag("p", f"Showing {page['total']} budget account(s).", " class='muted'")
    body += _table(["FY", "Fund", "Budget Unit", "Account", "Title", "Budget", "Spent", "Encumbered", "Available"], rows) if rows else _empty("No budget accounts found", "Import ledger activity with budget/account fields to populate Budget Accounts.")
    return _page(f"{department_name} Budget Accounts", "Budget accounts calculated from ledger activity.", body)


@bp.route("/budget-accounts/<int:budget_account_id>")
@login_required
def budget_account_detail(budget_account_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)
    if not has_budget_view(user_id):
        abort(403)
    account = get_budget_account_detail(budget_account_id)
    if not account:
        abort(404)
    if not can_access_department(user_id, account["department_name"]):
        abort(403)
    body = _table(["Field", "Value"], [[key, value] for key, value in account.items() if key not in {"activity", "purchase_orders"}])
    return _page(f"Budget Account {account.get('account_code')}", "Budget account rollup and related ledger activity.", body)
