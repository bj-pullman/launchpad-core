from __future__ import annotations

from flask import abort, flash, redirect, request, session, url_for

from .access_service import can_access_department
from .blueprint import bp


@bp.before_request
def redirect_legacy_transactions_routes():
    parts = [part for part in request.path.strip("/").split("/") if part]
    if len(parts) >= 3 and parts[0] == "finance" and parts[2] == "transactions":
        department_name = parts[1]
        user_id = session.get("user_id")
        if not user_id:
            abort(403)
        if not can_access_department(user_id, department_name):
            abort(403)
        flash("Transactions has been replaced by Ledger.", "info")
        return redirect(url_for("finance.ledger", department_name=department_name))
    return None
