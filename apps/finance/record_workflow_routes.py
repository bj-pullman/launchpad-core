from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from modules.core.auth.decorators import login_required
from modules.core.auth.session_policy import require_csrf
from .blueprint import bp
from .access_service import can_access_department, can_manage_department, has_budget_view
from . import ledger_review_service as ledger_review_data
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
    if request.args.get("paged") == "1" or request.args.get("all") == "1":
        response = jsonify(ledger_review_data.record_choices(
            department_name, request.args.get("q", ""), request.args.get("page", 1, type=int),
            all_records=request.args.get("all") == "1"))
    else:
        response = jsonify(workflow.record_options(department_name, request.args.get("q", "")))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/<department_name>/renewals/search")
@login_required
def record_renewal_search(department_name):
    require_department(department_name)
    return jsonify(renewal_options(department_name, request.args.get("q", "")))


@bp.route("/<department_name>/ledger/review", methods=["GET", "POST"])
@login_required
def ledger_review(department_name):
    user_id = require_department(department_name, request.method == "POST")
    ajax = request.headers.get("X-Ledger-Review") == "1"
    run_id = request.args.get("run_id", type=int)
    if "run_id" in request.args and (run_id is None or run_id <= 0):
        abort(404)
    import_info = None
    if run_id:
        try:
            import_info = ledger_review_data.get_import_context(department_name, run_id)
        except ValueError:
            abort(404)
    scope = request.args.get("scope", "import" if run_id else "all")
    if scope not in ("import", "all") or not run_id:
        scope = "all"
    scope_context = import_info if scope == "import" else None
    filters = {key: (request.args.get(key) or "").strip() for key in (
        "fiscal_year_code", "transaction_code", "vendor_q", "account_q", "po_number", "q")}
    status = request.args.get("review_status", "unresolved")
    filters["review_status"] = status if status in ledger_review_data.REVIEW_STATUSES else "unresolved"
    per_page = request.args.get("per_page", 25, type=int)
    if per_page not in ledger_review_data.PAGE_SIZES:
        per_page = 25
    page = max(1, request.args.get("page", 1, type=int))
    url_args = dict(department_name=department_name, run_id=run_id, scope=scope,
                    per_page=per_page, **filters)

    def page_url(number):
        return url_for("finance.ledger_review", page=number, **url_args)

    message = ""
    if request.method == "POST":
        require_csrf()
        ledger_id = request.form.get("ledger_id", type=int)
        action = request.form.get("action", "")
        row_version = request.form.get("row_version")
        try:
            if not ledger_id or row_version is None:
                raise ValueError("The transaction information is incomplete. Refresh the review.")
            record_id = workflow.review_action(
                department_name, ledger_id, action, user_id,
                request.form.get("record_id", type=int), expected_updated_at=row_version)
            if action == "link":
                message = f"Transaction #{ledger_id} linked to Record #{record_id}."
            elif action == "create":
                message = f"Record #{record_id} created and linked to transaction #{ledger_id}."
            elif action == "ignore":
                message = f"Transaction #{ledger_id} ignored."
            else:
                message = f"Transaction #{ledger_id} marked reviewed."
        except ValueError as exc:
            if ajax:
                response = jsonify(ok=False, message=str(exc))
                response.status_code = 409
                response.headers["Cache-Control"] = "no-store"
                return response
            flash(str(exc), "error")
            return redirect(page_url(page))
        if not ajax:
            flash(message, "success")
            return redirect(page_url(page))

    review = ledger_review_data.review_page(
        department_name, import_context=scope_context, filters=filters, page=page, per_page=per_page)
    can_manage = can_manage_department(user_id, department_name)
    context = dict(
        department_name=department_name, active_tab="ledger", can_manage=can_manage,
        can_view_budget=has_budget_view(user_id), run_id=run_id, scope=scope,
        filters=filters, review=review, import_info=import_info,
        overall_counts=ledger_review_data.review_counts(department_name),
        import_counts=ledger_review_data.review_counts(department_name, import_info) if import_info else None,
        fiscal_years=ledger_review_data.fiscal_year_options(department_name),
        initial_records=ledger_review_data.record_choices(department_name, all_records=True) if can_manage else dict(rows=[], page=1, has_more=False),
        current_url=page_url(review["page"]),
        reset_url=url_for("finance.ledger_review", department_name=department_name, run_id=run_id, scope=scope),
        page_links=dict(first=page_url(1), previous=page_url(max(1, review["page"] - 1)),
                        next=page_url(min(review["total_pages"], review["page"] + 1)), last=page_url(review["total_pages"])),
    )
    if ajax:
        response = jsonify(ok=True, message=message, url=context["current_url"],
                           html=render_template("finance/_ledger_review_results.html", **context))
        response.headers["Cache-Control"] = "no-store"
        return response
    return render_template("finance/ledger_review.html", **context)


@bp.post("/<department_name>/ledger/record-action")
@login_required
def ledger_record_action(department_name):
    """Use the same transactional linking/promotion workflow from the Ledger."""
    user_id = require_department(department_name, True)
    require_csrf()
    ledger_id = request.form.get("ledger_id", type=int)
    action = request.form.get("action")
    version = request.form.get("row_version")
    try:
        if not ledger_id or version is None or action not in ("link", "create"):
            raise ValueError("Choose a transaction and a valid Record action.")
        record_id = workflow.review_action(department_name, ledger_id, action, user_id,
            request.form.get("record_id", type=int), expected_updated_at=version)
    except ValueError as exc:
        response = jsonify(ok=False, message=str(exc))
        response.status_code = 409
    else:
        verb = "created and linked" if action == "create" else "linked"
        response = jsonify(ok=True, message=f"Record #{record_id} {verb} to transaction #{ledger_id}.",
                           record_url=url_for("finance.record_detail", record_id=record_id))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/<department_name>/records/<int:record_id>/renewal")
@login_required
def record_renewal_save(department_name, record_id):
    user_id = require_department(department_name, True)
    require_csrf()
    if request.form.get("is_renewal") != "on":
        flash("Choose Link Existing Renewal or Create Renewal.", "error")
        return redirect(url_for("finance.record_detail", record_id=record_id))
    try:
        renewal_from_record(record_id, department_name, user_id,
            mode=request.form.get("renewal_mode"), cycle_id=request.form.get("renewal_cycle_id", type=int),
            renewal_id=request.form.get("renewal_id", type=int), fiscal_year_id=request.form.get("fiscal_year_id", type=int),
            replace=request.form.get("replace_link") == "1")
        flash("Renewal linked to this Record.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("finance.record_detail", record_id=record_id))


@bp.post("/records/<int:record_id>/friendly-name")
@login_required
def record_friendly_name_save(record_id):
    from . import service
    from .db import finance_transaction
    record = service.get_record_by_id(record_id)
    if not record:
        abort(404)
    user_id = require_department(record["department_name"], True)
    require_csrf()
    with finance_transaction() as conn:
        current = conn.execute("SELECT status FROM finance_records WHERE id=?", (record_id,)).fetchone()
        if current["status"] == "deleted":
            abort(409)
        name = service.normalize_text(request.form.get("friendly_name"))
        now = service.utc_now_iso()
        conn.execute("UPDATE finance_records SET friendly_name=?, updated_at=? WHERE id=?", (name, now, record_id))
        conn.execute("""INSERT INTO finance_record_history
            (finance_record_id, event_type, summary, changed_by_user_id, changed_at)
            VALUES (?, 'updated', 'Friendly Record Name updated.', ?, ?)""", (record_id, user_id, now))
    flash("Friendly Record Name saved.", "success")
    return redirect(url_for("finance.record_detail", record_id=record_id))


@bp.post("/records/<int:record_id>/renewal/unlink")
@login_required
def record_renewal_unlink(record_id):
    from . import service, renewal_service
    from .db import finance_transaction
    record = service.get_record_by_id(record_id)
    if not record:
        abort(404)
    user_id = require_department(record["department_name"], True)
    require_csrf()
    with finance_transaction() as conn:
        current = conn.execute("SELECT status FROM finance_records WHERE id=?", (record_id,)).fetchone()
        if current["status"] in ("deleted", "archived"):
            abort(409)
        link = renewal_service.get_record_renewal_link(record_id)
        if link:
            renewal_service.unlink_record_from_renewal_cycle(renewal_cycle_id=link["renewal_cycle_id"],
                finance_record_id=record_id, changed_by_user_id=user_id)
    flash("Renewal unlinked.", "success")
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
