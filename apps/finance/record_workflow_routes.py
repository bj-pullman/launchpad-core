from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from modules.core.auth.decorators import login_required
from modules.core.auth.session_policy import require_csrf
from .blueprint import bp
from .access_service import can_access_department, can_manage_department
from . import record_workflow_service as workflow
from .record_renewal_service import renewal_options, renewal_from_record


def require_department(department, manage=False):
    user_id = session.get("user_id")
    if not user_id or not can_access_department(user_id, department):
        abort(403)
    if manage and not can_manage_department(user_id, department):
        abort(403)
    return user_id


@bp.get("/<department_name>/records/po-preview")
@login_required
def record_po_preview(department_name):
    require_department(department_name)
    return jsonify(workflow.po_preview(department_name, request.args.get("po", ""), request.args.get("exclude", type=int)))


@bp.get("/<department_name>/records/search")
@login_required
def record_search(department_name):
    require_department(department_name)
    return jsonify(workflow.record_options(department_name, request.args.get("q", "")))


@bp.get("/<department_name>/renewals/search")
@login_required
def record_renewal_search(department_name):
    require_department(department_name)
    return jsonify(renewal_options(department_name, request.args.get("q", "")))


@bp.route("/<department_name>/ledger/review", methods=["GET", "POST"])
@login_required
def ledger_review(department_name):
    user_id = require_department(department_name, request.method == "POST")
    run_id = request.args.get("run_id", type=int)
    if request.method == "POST":
        require_csrf()
        try:
            workflow.review_action(department_name, request.form.get("ledger_id", type=int),
                                   request.form.get("action"), user_id, request.form.get("record_id", type=int))
            flash("Ledger review saved.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("finance.ledger_review", department_name=department_name, run_id=run_id))
    return render_template("finance/ledger_review.html", department_name=department_name,
        review=workflow.review_rows(department_name, run_id, max(1, request.args.get("page", 1, type=int))),
        summary=workflow.import_summary(department_name, run_id) if run_id else None,
        run_id=run_id, active_tab="ledger", can_manage=can_manage_department(user_id, department_name))


@bp.post("/<department_name>/records/<int:record_id>/renewal")
@login_required
def record_renewal_save(department_name, record_id):
    user_id = require_department(department_name, True)
    require_csrf()
    if request.form.get("is_renewal") != "on":
        flash("Select This Record is a Renewal and choose how to link it.", "error")
        return redirect(url_for("finance.record_detail", record_id=record_id))
    try:
        renewal_from_record(record_id, department_name, user_id,
            mode=request.form.get("renewal_mode"), cycle_id=request.form.get("renewal_cycle_id", type=int),
            renewal_id=request.form.get("renewal_id", type=int), fiscal_year_id=request.form.get("fiscal_year_id", type=int))
        flash("Renewal linked to this Record.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("finance.record_detail", record_id=record_id))


def save_form_renewal(record_id, department, user_id):
    preview = workflow.po_preview(department, request.form.get("po_number", ""), record_id)
    if preview["duplicates"]:
        names = ", ".join(f"{r['name']} (Record {r['id']})" for r in preview["duplicates"])
        flash(f"Possible duplicate Record: PO {preview['po']} is also used by {names}. Ambiguous Ledger rows remain for review.", "warning")
    if request.form.get("is_renewal") != "on":
        return
    require_csrf()
    try:
        renewal_from_record(record_id, department, user_id,
            mode=request.form.get("renewal_mode"), cycle_id=request.form.get("renewal_cycle_id", type=int),
            renewal_id=request.form.get("renewal_id", type=int), fiscal_year_id=request.form.get("fiscal_year_id", type=int))
    except ValueError as exc:
        flash(f"Record saved; Renewal needs attention: {exc}", "error")
