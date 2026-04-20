from click import Path
from flask import abort, redirect, render_template, request, session, url_for, send_file, flash, Response
import csv
from modules.core.auth.decorators import login_required
from io import StringIO

from .access_service import (
    can_access_department,
    can_manage_department,
    has_budget_view,
    has_finance_admin,
    list_accessible_departments_for_user,
    can_access_department,
    can_manage_department,
    has_budget_view,
    can_access_budget_department,
)
from .blueprint import bp
from .service import (
    FINANCE_UPLOADS_DIR,
    archive_record,
    create_record,
    create_vendor,
    delete_attachment,
    delete_record,
    get_attachment_by_id,
    get_finance_dashboard_summary,
    get_record_by_id,
    get_vendor_by_id,
    list_active_records_for_department,
    list_archived_records_for_department,
    list_attachments_for_record,
    list_categories,
    list_deleted_records_for_department,
    list_history_for_record,
    list_vendors_all,
    purge_deleted_records_older_than,
    restore_archived_record,
    restore_deleted_record,
    save_attachment,
    sync_departments_from_users,
    update_record,
    update_vendor,
    archive_vendor,
    delete_vendor,
    list_active_vendors,
    list_archived_vendors,
    list_deleted_vendors,
    list_records_for_vendor,
    restore_vendor,
    get_vendor_department_context,
    list_import_profiles,
    list_import_runs,
    list_import_sources,
    create_import_run,
    get_import_run_by_id,
    get_import_target_fields,
    read_import_headers,
    save_import_upload,
    update_import_run_status,
    create_import_profile,
    replace_import_profile_fields,
    get_record_template_headers,
    get_vendor_template_headers,
    get_import_profile_by_name,
    execute_records_import,
    get_import_profile_fields,
    list_import_run_errors,
    set_import_run_profile,
    get_import_profile_field_map,
    validate_records_import,
    infer_import_field_map,
    maybe_send_renewal_notification_for_record,
    get_budget_summary_for_department,
    get_budget_breakdown_for_department,
    get_budget_year_options_for_department,
)

@bp.route("/")
@login_required
def index():
    sync_departments_from_users()

    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    departments = list_accessible_departments_for_user(user_id)

    if not departments:
        return render_template(
            "finance/index.html",
            departments=[],
            active_tab="home",
            no_departments_assigned=True,
            is_finance_admin=has_finance_admin(user_id),
            explicit_permissions_notice=(
                "Finance access requires both a role and department scope. "
                "Budget access is separate and must be assigned explicitly."
            ),
        )

    if len(departments) == 1:
        return redirect(
            url_for(
                "finance.department_overview",
                department_name=departments[0]["department_name"],
            )
        )

    return render_template(
        "finance/index.html",
        departments=departments,
        active_tab="home",
        no_departments_assigned=False,
        is_finance_admin=has_finance_admin(user_id),
        explicit_permissions_notice=(
            "Finance access requires both a role and department scope. "
            "Budget access is separate and must be assigned explicitly."
        ),
    )


@bp.route("/<department_name>")
@login_required
def department_overview(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    summary = get_finance_dashboard_summary(department_name)

    return render_template(
        "finance/department_overview.html",
        department_name=department_name,
        active_tab="overview",
        dashboard_summary=summary,
        can_view_budget=has_budget_view(user_id),
        explicit_permissions_notice=(
            "Finance access requires both a role and department scope. "
            "Budget access is separate and must be assigned explicitly."
        ),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/<department_name>/records")
@login_required
def records(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/records.html",
        department_name=department_name,
        active_tab="records",
        records=list_active_records_for_department(department_name),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/<department_name>/records/archived")
@login_required
def records_archived(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/records_archived.html",
        department_name=department_name,
        active_tab="archived",
        records=list_archived_records_for_department(department_name),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/<department_name>/records/deleted")
@login_required
def records_deleted(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/records_deleted.html",
        department_name=department_name,
        active_tab="deleted",
        records=list_deleted_records_for_department(department_name),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/<department_name>/records/new", methods=["GET", "POST"])
@login_required
def record_create(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    if request.method == "POST":
        vendor_id = request.form.get("vendor_id", type=int)
        category_id = request.form.get("category_id", type=int)
        notify_days_before = request.form.get("notify_days_before", type=int) or 30

        use_purchase_date_as_start = request.form.get("use_purchase_date_as_start") == "1"
        term_length = request.form.get("term_length", type=int)
        term_unit = (request.form.get("term_unit") or "").strip()

        cost = (request.form.get("cost") or "").strip() or None

        record_id = create_record(
            record_type=(request.form.get("record_type") or "").strip(),
            title=(request.form.get("title") or "").strip(),
            department_name=department_name,
            vendor_id=vendor_id,
            category_id=category_id,
            account_code=(request.form.get("account_code") or "").strip(),
            po_number=(request.form.get("po_number") or "").strip(),
            purchase_date=(request.form.get("purchase_date") or "").strip(),
            service_start_date=(request.form.get("service_start_date") or "").strip(),
            use_purchase_date_as_start=use_purchase_date_as_start,
            term_length=term_length,
            term_unit=term_unit,
            expiration_date=(request.form.get("expiration_date") or "").strip(),
            renewal_date=(request.form.get("renewal_date") or "").strip(),
            notify_days_before=notify_days_before,
            notification_recipients=(request.form.get("notification_recipients") or "").strip(),
            status=(request.form.get("status") or "").strip(),
            cost=cost,
            notes=(request.form.get("notes") or "").strip(),
            created_by_user_id=user_id,
        )

        uploads = request.files.getlist("attachment_files")

        for upload in uploads:
            if not upload or not upload.filename:
                continue

            file_bytes = upload.read()
            mime_type = upload.mimetype or ""

            if not file_bytes:
                continue

            save_attachment(
                finance_record_id=record_id,
                original_filename=upload.filename,
                file_bytes=file_bytes,
                mime_type=mime_type,
                document_type="other",
                uploaded_by_user_id=user_id,
            )

        sent_now, send_message = maybe_send_renewal_notification_for_record(
            record_id,
            changed_by_user_id=user_id,
        )

        if sent_now:
            flash(f"Record created successfully. {send_message}", "success")
        else:
            flash("Record created successfully.", "success")

        return redirect(url_for("finance.record_detail", record_id=record_id))

    return render_template(
        "finance/record_form.html",
        department_name=department_name,
        active_tab="records",
        vendors=list_vendors_all(),
        categories=list_categories(),
        form_mode="create",
    )


@bp.route("/records/<int:record_id>")
@login_required
def record_detail(record_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    record = get_record_by_id(record_id)
    if not record:
        abort(404)

    if not can_access_department(user_id, record["department_name"]):
        abort(403)

    return render_template(
        "finance/record_detail.html",
        record=record,
        department_name=record["department_name"],
        active_tab=(
            "archived" if record["status"] == "archived"
            else "deleted" if record["status"] == "deleted"
            else "records"
        ),
        attachments=list_attachments_for_record(record_id),
        history=list_history_for_record(record_id),
        can_manage=can_manage_department(user_id, record["department_name"]),
    )


@bp.route("/records/<int:record_id>/edit", methods=["GET", "POST"])
@login_required
def record_edit(record_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    record = get_record_by_id(record_id)
    if not record:
        abort(404)

    department_name = record["department_name"]

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    if request.method == "POST":
        vendor_id = request.form.get("vendor_id", type=int)
        category_id = request.form.get("category_id", type=int)
        notify_days_before = request.form.get("notify_days_before", type=int) or 30

        use_purchase_date_as_start = request.form.get("use_purchase_date_as_start") == "1"
        term_length = request.form.get("term_length", type=int)
        term_unit = (request.form.get("term_unit") or "").strip()

        cost = (request.form.get("cost") or "").strip() or None

        update_record(
            record_id=record_id,
            record_type=(request.form.get("record_type") or "").strip(),
            title=(request.form.get("title") or "").strip(),
            department_name=department_name,
            vendor_id=vendor_id,
            category_id=category_id,
            account_code=(request.form.get("account_code") or "").strip(),
            po_number=(request.form.get("po_number") or "").strip(),
            purchase_date=(request.form.get("purchase_date") or "").strip(),
            service_start_date=(request.form.get("service_start_date") or "").strip(),
            use_purchase_date_as_start=use_purchase_date_as_start,
            term_length=term_length,
            term_unit=term_unit,
            expiration_date=(request.form.get("expiration_date") or "").strip(),
            renewal_date=(request.form.get("renewal_date") or "").strip(),
            notify_days_before=notify_days_before,
            notification_recipients=(request.form.get("notification_recipients") or "").strip(),
            status=(request.form.get("status") or "").strip(),
            cost=cost,
            notes=(request.form.get("notes") or "").strip(),
            changed_by_user_id=user_id,
        )

        sent_now, send_message = maybe_send_renewal_notification_for_record(
            record_id,
            changed_by_user_id=user_id,
        )

        if sent_now:
            flash(f"Record updated successfully. {send_message}", "success")
        else:
            flash("Record updated successfully.", "success")

        return redirect(url_for("finance.record_detail", record_id=record_id))

    return render_template(
        "finance/record_form.html",
        department_name=department_name,
        active_tab="records",
        vendors=list_vendors_all(),
        categories=list_categories(),
        form_mode="edit",
        record=record,
    )


@bp.route("/records/<int:record_id>/archive", methods=["POST"])
@login_required
def record_archive(record_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    record = get_record_by_id(record_id)
    if not record:
        abort(404)

    if not can_access_department(user_id, record["department_name"]):
        abort(403)

    if not can_manage_department(user_id, record["department_name"]):
        abort(403)

    archive_record(record_id, changed_by_user_id=user_id)
    flash("Record archived successfully.", "success")
    return redirect(url_for("finance.records_archived", department_name=record["department_name"]))


@bp.route("/records/<int:record_id>/restore-archived", methods=["POST"])
@login_required
def record_restore_archived(record_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    record = get_record_by_id(record_id)
    if not record:
        abort(404)

    if not can_access_department(user_id, record["department_name"]):
        abort(403)

    if not can_manage_department(user_id, record["department_name"]):
        abort(403)

    restore_archived_record(record_id, changed_by_user_id=user_id)
    flash("Archived record restored successfully.", "success")
    return redirect(url_for("finance.record_detail", record_id=record_id))


@bp.route("/records/<int:record_id>/delete", methods=["POST"])
@login_required
def record_delete(record_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    record = get_record_by_id(record_id)
    if not record:
        abort(404)

    department_name = record["department_name"]

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    delete_record(record_id, deleted_by_user_id=user_id)
    flash("Record moved to deleted successfully.", "success")
    return redirect(url_for("finance.records_deleted", department_name=department_name))


@bp.route("/records/<int:record_id>/restore-deleted", methods=["POST"])
@login_required
def record_restore_deleted(record_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    record = get_record_by_id(record_id)
    if not record:
        abort(404)

    if not can_access_department(user_id, record["department_name"]):
        abort(403)

    if not can_manage_department(user_id, record["department_name"]):
        abort(403)

    restore_deleted_record(record_id, changed_by_user_id=user_id)
    flash("Deleted record restored successfully.", "success")
    return redirect(url_for("finance.record_detail", record_id=record_id))


@bp.route("/<department_name>/records/deleted/purge", methods=["POST"])
@login_required
def records_deleted_purge(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    purged = purge_deleted_records_older_than(30)
    flash(f"Purged {purged} deleted record(s) older than 30 days.", "success")
    return redirect(url_for("finance.records_deleted", department_name=department_name))

@bp.route("/<department_name>/records/bulk-archive", methods=["POST"])
@login_required
def records_bulk_archive(department_name: str):
    user_id = session.get("user_id")

    if not can_manage_department(user_id, department_name):
        abort(403)

    ids = request.form.get("ids", "")
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]

    for record_id in id_list:
        archive_record(record_id)

    flash(f"{len(id_list)} record(s) archived.", "success")

    return redirect(url_for("finance.records", department_name=department_name))

@bp.route("/<department_name>/records/bulk-delete", methods=["POST"])
@login_required
def records_bulk_delete(department_name: str):
    user_id = session.get("user_id")

    if not can_manage_department(user_id, department_name):
        abort(403)

    ids = request.form.get("ids", "")
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]

    for record_id in id_list:
        delete_record(record_id)

    flash(f"{len(id_list)} record(s) deleted.", "success")

    return redirect(url_for("finance.records", department_name=department_name))

@bp.route("/<department_name>/records/bulk-restore", methods=["POST"])
@login_required
def records_bulk_restore(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    ids = request.form.get("ids", "")
    record_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]

    restored_count = 0
    for record_id in record_ids:
        record = get_record_by_id(record_id)
        if not record:
            continue
        if record["department_name"] != department_name:
            continue

        if record["status"] == "archived":
            ok = restore_archived_record(record_id, changed_by_user_id=user_id)
        elif record["status"] == "deleted":
            ok = restore_deleted_record(record_id, changed_by_user_id=user_id)
        else:
            ok = False

        if ok:
            restored_count += 1

    flash(f"{restored_count} record(s) restored successfully.", "success")
    return redirect(url_for("finance.records_archived", department_name=department_name))

@bp.route("/<department_name>/vendors")
@login_required
def vendors(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/vendors.html",
        department_name=department_name,
        active_tab="vendors",
        vendor_tab="active",
        vendors=list_active_vendors(),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/<department_name>/vendors/archived")
@login_required
def vendors_archived(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/vendors_archived.html",
        department_name=department_name,
        active_tab="vendors",
        vendor_tab="archived",
        vendors=list_archived_vendors(),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/<department_name>/vendors/deleted")
@login_required
def vendors_deleted(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/vendors_deleted.html",
        department_name=department_name,
        active_tab="vendors",
        vendor_tab="deleted",
        vendors=list_deleted_vendors(),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/<department_name>/vendors/new", methods=["GET", "POST"])
@login_required
def vendor_create(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    if request.method == "POST":
        vendor_id = create_vendor(
            vendor_name=(request.form.get("vendor_name") or "").strip(),
            vendor_code=(request.form.get("vendor_code") or "").strip(),
            website=(request.form.get("website") or "").strip(),
            main_phone=(request.form.get("main_phone") or "").strip(),
            billing_email=(request.form.get("billing_email") or "").strip(),
            support_email=(request.form.get("support_email") or "").strip(),
            sales_contact_name=(request.form.get("sales_contact_name") or "").strip(),
            sales_contact_email=(request.form.get("sales_contact_email") or "").strip(),
            notes=(request.form.get("notes") or "").strip(),
        )
        flash("Vendor created successfully.", "success")
        return redirect(url_for("finance.vendor_detail", vendor_id=vendor_id))

    return render_template(
        "finance/vendor_form.html",
        department_name=department_name,
        active_tab="vendors",
        vendor_tab="active",
        form_mode="create",
    )


@bp.route("/vendors/<int:vendor_id>")
@login_required
def vendor_detail(vendor_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        abort(404)

    related_records = list_records_for_vendor(vendor_id)

    user_departments = {
        item["department_name"]
        for item in list_accessible_departments_for_user(user_id)
    }

    visible_related_records = [
        record for record in related_records
        if record["department_name"] in user_departments
    ]

    if not visible_related_records and not has_finance_admin(user_id):
        abort(403)

    department_name = (
        visible_related_records[0]["department_name"]
        if visible_related_records
        else next(iter(user_departments), None)
    )
    if not department_name:
        abort(403)

    return render_template(
        "finance/vendor_detail.html",
        vendor=vendor,
        related_records=visible_related_records,
        department_name=department_name,
        active_tab="vendors",
        vendor_tab=(
            "archived" if vendor.get("status") == "archived"
            else "deleted" if vendor.get("status") == "deleted"
            else "active"
        ),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/vendors/<int:vendor_id>/edit", methods=["GET", "POST"])
@login_required
def vendor_edit(vendor_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        abort(404)

    related_records = list_records_for_vendor(vendor_id)
    department_name = related_records[0]["department_name"] if related_records else None

    if not department_name:
        departments = list_accessible_departments_for_user(user_id)
        department_name = departments[0]["department_name"] if departments else None

    if not department_name:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    if request.method == "POST":
        update_vendor(
            vendor_id=vendor_id,
            vendor_name=(request.form.get("vendor_name") or "").strip(),
            vendor_code=(request.form.get("vendor_code") or "").strip(),
            website=(request.form.get("website") or "").strip(),
            main_phone=(request.form.get("main_phone") or "").strip(),
            billing_email=(request.form.get("billing_email") or "").strip(),
            support_email=(request.form.get("support_email") or "").strip(),
            sales_contact_name=(request.form.get("sales_contact_name") or "").strip(),
            sales_contact_email=(request.form.get("sales_contact_email") or "").strip(),
            status=(request.form.get("status") or "").strip() or "active",
            notes=(request.form.get("notes") or "").strip(),
        )
        flash("Vendor updated successfully.", "success")
        return redirect(url_for("finance.vendor_detail", vendor_id=vendor_id))

    return render_template(
        "finance/vendor_form.html",
        vendor=vendor,
        department_name=department_name,
        active_tab="vendors",
        vendor_tab=(
            "archived" if vendor.get("status") == "archived"
            else "deleted" if vendor.get("status") == "deleted"
            else "active"
        ),
        form_mode="edit",
    )


@bp.route("/vendors/<int:vendor_id>/archive", methods=["POST"])
@login_required
def vendor_archive(vendor_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        abort(404)

    department_name = get_vendor_department_context(
        user_departments=list_accessible_departments_for_user(user_id),
        vendor_id=vendor_id,
        posted_department_name=request.form.get("department_name"),
    )
    if not department_name:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    archive_vendor(vendor_id)
    flash("Vendor archived successfully.", "success")
    return redirect(url_for("finance.vendor_detail", vendor_id=vendor_id))


@bp.route("/vendors/<int:vendor_id>/delete", methods=["POST"])
@login_required
def vendor_delete(vendor_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        abort(404)

    department_name = get_vendor_department_context(
        user_departments=list_accessible_departments_for_user(user_id),
        vendor_id=vendor_id,
        posted_department_name=request.form.get("department_name"),
    )

    if not department_name:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    delete_vendor(vendor_id)
    flash("Vendor moved to deleted successfully.", "success")
    return redirect(url_for("finance.vendors_deleted", department_name=department_name))


@bp.route("/vendors/<int:vendor_id>/restore", methods=["POST"])
@login_required
def vendor_restore(vendor_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        abort(404)

    department_name = get_vendor_department_context(
        user_departments=list_accessible_departments_for_user(user_id),
        vendor_id=vendor_id,
        posted_department_name=request.form.get("department_name"),
    )

    if not department_name:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    restore_vendor(vendor_id)
    flash("Vendor restored successfully.", "success")
    return redirect(url_for("finance.vendor_detail", vendor_id=vendor_id))

@bp.route("/<department_name>/vendors/bulk-archive", methods=["POST"])
@login_required
def vendors_bulk_archive(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    ids = request.form.get("ids", "")
    vendor_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]

    archived_count = 0

    for vendor_id in vendor_ids:
        vendor = get_vendor_by_id(vendor_id)
        if not vendor:
            continue

        if archive_vendor(vendor_id):
            archived_count += 1

    flash(f"{archived_count} vendor(s) archived successfully.", "success")
    return redirect(url_for("finance.vendors", department_name=department_name))


@bp.route("/<department_name>/vendors/bulk-delete", methods=["POST"])
@login_required
def vendors_bulk_delete(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    ids = request.form.get("ids", "")
    vendor_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]

    deleted_count = 0

    for vendor_id in vendor_ids:
        vendor = get_vendor_by_id(vendor_id)
        if not vendor:
            continue

        if delete_vendor(vendor_id):
            deleted_count += 1

    flash(f"{deleted_count} vendor(s) moved to deleted successfully.", "success")
    return redirect(url_for("finance.vendors", department_name=department_name))


@bp.route("/<department_name>/vendors/bulk-restore", methods=["POST"])
@login_required
def vendors_bulk_restore(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    ids = request.form.get("ids", "")
    vendor_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]

    restored_count = 0

    for vendor_id in vendor_ids:
        vendor = get_vendor_by_id(vendor_id)
        if not vendor:
            continue

        if restore_vendor(vendor_id):
            restored_count += 1

    flash(f"{restored_count} vendor(s) restored successfully.", "success")
    return redirect(url_for("finance.vendors", department_name=department_name))


@bp.route("/records/<int:record_id>/attachments/upload", methods=["POST"])
@login_required
def upload_attachment(record_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    record = get_record_by_id(record_id)
    if not record:
        abort(404)

    department_name = record["department_name"]

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_manage_department(user_id, department_name):
        abort(403)

    upload = request.files.get("attachment_files")
    document_type = (request.form.get("document_type") or "").strip()

    if not document_type:
        flash("Please choose an attachment type.", "error")
        return redirect(url_for("finance.record_detail", record_id=record_id))

    if not upload or not upload.filename:
        flash("No attachment selected.", "error")
        return redirect(url_for("finance.record_detail", record_id=record_id))

    file_bytes = upload.read()
    mime_type = upload.mimetype or ""

    if not file_bytes:
        flash("The selected attachment was empty.", "error")
        return redirect(url_for("finance.record_detail", record_id=record_id))

    try:
        save_attachment(
            finance_record_id=record_id,
            original_filename=upload.filename,
            file_bytes=file_bytes,
            mime_type=mime_type,
            document_type=document_type,
            uploaded_by_user_id=user_id,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("finance.record_detail", record_id=record_id))

    flash("Attachment uploaded successfully.", "success")
    return redirect(url_for("finance.record_detail", record_id=record_id))


@bp.route("/attachments/<int:attachment_id>/download")
@login_required
def download_attachment(attachment_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    attachment = get_attachment_by_id(attachment_id)
    if not attachment:
        abort(404)

    record = get_record_by_id(attachment["finance_record_id"])
    if not record:
        abort(404)

    if not can_access_department(user_id, record["department_name"]):
        abort(403)

    file_path = FINANCE_UPLOADS_DIR / attachment["stored_name"]
    if not file_path.exists():
        abort(404)

    return send_file(
        file_path,
        mimetype=attachment["mime_type"],
        as_attachment=True,
        download_name=attachment["file_name"],
    )


@bp.route("/attachments/<int:attachment_id>/view")
@login_required
def view_attachment(attachment_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    attachment = get_attachment_by_id(attachment_id)
    if not attachment:
        abort(404)

    record = get_record_by_id(attachment["finance_record_id"])
    if not record:
        abort(404)

    if not can_access_department(user_id, record["department_name"]):
        abort(403)

    file_path = FINANCE_UPLOADS_DIR / attachment["stored_name"]
    if not file_path.exists():
        abort(404)

    suffix = Path(attachment["file_name"]).suffix.lower()

    inline_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}

    if suffix in inline_extensions:
        return send_file(
            file_path,
            mimetype=attachment["mime_type"] or "application/octet-stream",
            as_attachment=False,
            download_name=attachment["file_name"],
        )

    return send_file(
        file_path,
        mimetype=attachment["mime_type"] or "application/octet-stream",
        as_attachment=True,
        download_name=attachment["file_name"],
    )


@bp.route("/attachments/<int:attachment_id>/delete", methods=["POST"])
@login_required
def delete_attachment_route(attachment_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    attachment = get_attachment_by_id(attachment_id)
    if not attachment:
        abort(404)

    record = get_record_by_id(attachment["finance_record_id"])
    if not record:
        abort(404)

    if not can_access_department(user_id, record["department_name"]):
        abort(403)

    if not can_manage_department(user_id, record["department_name"]):
        abort(403)

    delete_attachment(attachment_id, deleted_by_user_id=user_id)
    flash("Attachment deleted successfully.", "success")
    return redirect(url_for("finance.record_detail", record_id=record["id"]))

@bp.route("/<department_name>/imports", methods=["GET", "POST"])
@login_required
def imports(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    can_manage = can_manage_department(user_id, department_name)

    if request.method == "POST":
        if not can_manage:
            abort(403)

        import_type = (request.form.get("import_type") or "").strip().lower()
        profile_id = request.form.get("profile_id", type=int)
        upload = request.files.get("import_file")

        if import_type not in {"records", "vendors"}:
            flash("Please choose a valid import type.", "error")
            return redirect(url_for("finance.imports", department_name=department_name))

        if not upload or not upload.filename:
            flash("Please choose a file to import.", "error")
            return redirect(url_for("finance.imports", department_name=department_name))

        file_bytes = upload.read()
        if not file_bytes:
            flash("The selected file was empty.", "error")
            return redirect(url_for("finance.imports", department_name=department_name))

        try:
            stored_filename = save_import_upload(upload.filename, file_bytes)

            run_id = create_import_run(
                import_type=import_type,
                source_type="manual_upload",
                profile_id=profile_id,
                original_filename=upload.filename,
                stored_filename=stored_filename,
                status="uploaded",
                started_by_user_id=user_id,
            )

            headers = read_import_headers(stored_filename)

            update_import_run_status(
                run_id,
                status="preview_ready",
                run_notes=f"Detected {len(headers)} source column(s).",
            )

            return redirect(
                url_for(
                    "finance.imports_mapping",
                    department_name=department_name,
                    run_id=run_id,
                )
            )

        except Exception as exc:
            flash(f"Import upload failed: {exc}", "error")
            return redirect(url_for("finance.imports", department_name=department_name))

    return render_template(
        "finance/imports_upload.html",
        department_name=department_name,
        active_tab="overview",
        import_tab="upload",
        profiles=list_import_profiles(),
        can_manage=can_manage,
    )


@bp.route("/<department_name>/imports/profiles")
@login_required
def imports_profiles(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/imports_profiles.html",
        department_name=department_name,
        active_tab="overview",
        import_tab="profiles",
        profiles=list_import_profiles(),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/<department_name>/imports/history")
@login_required
def imports_history(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/imports_history.html",
        department_name=department_name,
        active_tab="overview",
        import_tab="history",
        import_runs=list_import_runs(),
        can_manage=can_manage_department(user_id, department_name),
    )


@bp.route("/<department_name>/imports/sftp")
@login_required
def imports_sftp(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    return render_template(
        "finance/imports_sftp.html",
        department_name=department_name,
        active_tab="overview",
        import_tab="sftp",
        import_sources=list_import_sources(),
        can_manage=can_manage_department(user_id, department_name),
    )

@bp.route("/<department_name>/imports/runs/<int:run_id>/mapping", methods=["GET", "POST"])
@login_required
def imports_mapping(department_name: str, run_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    run = get_import_run_by_id(run_id)
    if not run:
        abort(404)

    try:
        source_headers = read_import_headers(run["stored_filename"])
    except Exception as exc:
        flash(f"Could not read import headers: {exc}", "error")
        return redirect(url_for("finance.imports", department_name=department_name))

    target_fields = get_import_target_fields(run["import_type"])

    if request.method == "POST":
        if not can_manage_department(user_id, department_name):
            abort(403)

        save_profile = request.form.get("save_profile") == "1"
        profile_name = (request.form.get("profile_name") or "").strip()

        profile_id = run.get("profile_id")

        if save_profile:
            if not profile_name:
                flash("Enter a profile name or leave Save as Profile unchecked.", "error")
                return render_template(
                    "finance/imports_mapping.html",
                    department_name=department_name,
                    active_tab="overview",
                    import_tab="upload",
                    run=run,
                    source_headers=source_headers,
                    target_fields=target_fields,
                    selected_mappings=get_import_profile_field_map(profile_id) if profile_id else {},
                    can_manage=can_manage_department(user_id, department_name),
                )

            existing_profile = get_import_profile_by_name(profile_name)
            if existing_profile:
                profile_id = existing_profile["id"]
            else:
                profile_id = create_import_profile(
                    profile_name=profile_name,
                    source_type=run["source_type"],
                    target_area=run["import_type"],
                    description=f"Saved from import run #{run_id}",
                    created_by_user_id=user_id,
                )

        elif not profile_id:
            temp_profile_name = f"_run_{run_id}_mapping"
            temp_profile = get_import_profile_by_name(temp_profile_name)
            if temp_profile:
                profile_id = temp_profile["id"]
            else:
                profile_id = create_import_profile(
                    profile_name=temp_profile_name,
                    source_type=run["source_type"],
                    target_area=run["import_type"],
                    description=f"Temporary mapping for import run #{run_id}",
                    created_by_user_id=user_id,
                )

        mappings = []
        for field in target_fields:
            selected_source = (request.form.get(f"map_{field['field_name']}") or "").strip()
            mappings.append(
                {
                    "source_column_name": selected_source or None,
                    "target_field_name": field["field_name"],
                    "transform_rule": None,
                    "default_value": None,
                    "required": field["required"],
                    "ignore_field": not bool(selected_source),
                }
            )

        replace_import_profile_fields(profile_id, mappings)
        set_import_run_profile(run_id, profile_id)

        update_import_run_status(
            run_id,
            status="mapping_saved",
            run_notes="Mapping saved for validation.",
        )

        return redirect(
            url_for(
                "finance.imports_validate",
                department_name=department_name,
                run_id=run_id,
            )
        )

    selected_mappings = {}

    if run.get("profile_id"):
        selected_mappings = get_import_profile_field_map(run["profile_id"])

    if not selected_mappings:
        selected_mappings = infer_import_field_map(source_headers, run["import_type"])

    auto_mapping_used = False

    selected_mappings = {}
    if run.get("profile_id"):
        selected_mappings = get_import_profile_field_map(run["profile_id"])

    if not selected_mappings:
        selected_mappings = infer_import_field_map(source_headers, run["import_type"])
        auto_mapping_used = bool(selected_mappings)

    return render_template(
        "finance/imports_mapping.html",
        department_name=department_name,
        active_tab="overview",
        import_tab="upload",
        run=run,
        source_headers=source_headers,
        target_fields=target_fields,
        selected_mappings=selected_mappings,
        can_manage=can_manage_department(user_id, department_name),
        auto_mapping_used=auto_mapping_used,
    )

@bp.route("/<department_name>/imports/template/<string:import_type>")
@login_required
def imports_template_download(department_name: str, import_type: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    import_type = (import_type or "").strip().lower()

    if import_type == "vendors":
        headers = get_vendor_template_headers()
        filename = "finance_vendors_template.csv"
    elif import_type == "records":
        headers = get_record_template_headers()
        filename = "finance_records_template.csv"
    else:
        abort(404)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response

@bp.route("/<department_name>/imports/runs/<int:run_id>/validate", methods=["GET", "POST"])
@login_required
def imports_validate(department_name: str, run_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    run = get_import_run_by_id(run_id)
    if not run:
        abort(404)

    profile_id = run.get("profile_id")
    if not profile_id:
        flash("Complete mapping before validation.", "error")
        return redirect(
            url_for("finance.imports_mapping", department_name=department_name, run_id=run_id)
        )

    if run["import_type"] != "records":
        flash("Record validation is built first. Vendor validation is next.", "error")
        return redirect(url_for("finance.imports", department_name=department_name))

    validation = validate_records_import(
        run_id=run_id,
        profile_id=profile_id,
        default_department_name=department_name,
        preview_limit=20,
    )

    if request.method == "POST":
        if not can_manage_department(user_id, department_name):
            abort(403)

        if validation["valid_rows"] <= 0:
            flash("There are no valid rows to import.", "error")
            return redirect(
                url_for("finance.imports_validate", department_name=department_name, run_id=run_id)
            )

        try:
            result = execute_records_import(
                run_id=run_id,
                profile_id=profile_id,
                default_department_name=department_name,
                created_by_user_id=user_id,
            )

            flash(
                f"Import finished. Created {result['created_rows']} record(s), "
                f"created {result['vendors_created']} vendor(s), "
                f"sent {result.get('notifications_sent', 0)} notification(s), "
                f"skipped {result['skipped_rows']}, errors {result['error_rows']}.",
                "success",
            )
            
            if run["import_type"] == "records":
                return redirect(url_for("finance.records", department_name=department_name))
            elif run["import_type"] == "vendors":
                return redirect(url_for("finance.vendors", department_name=department_name))

            return redirect(url_for("finance.imports_history", department_name=department_name))

        except Exception as exc:
            flash(f"Import execution failed: {exc}", "error")
            return redirect(
                url_for("finance.imports_validate", department_name=department_name, run_id=run_id)
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

@bp.route("/imports/<int:run_id>/errors/export")
@login_required
def export_import_errors(run_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    run = get_import_run_by_id(run_id)
    if not run:
        abort(404)

    department_name = (run.get("department_name") or "").strip()
    if department_name and not can_access_department(user_id, department_name):
        abort(403)

    errors = list_import_run_errors(run_id)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Row Number", "Source Identifier", "Error Message", "Created At"])

    for item in errors:
        writer.writerow([
            item.get("row_number") or "",
            item.get("source_identifier") or "",
            item.get("error_message") or "",
            item.get("created_at") or "",
        ])

    csv_data = output.getvalue()
    output.close()

    response = Response(csv_data, mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=finance-import-errors-run-{run_id}.csv"
    return response

@bp.route("/<department_name>/budget")
@login_required
def budget(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_access_budget_department(user_id, department_name):
        abort(403)

    year = request.args.get("year", type=int)
    group_by = (request.args.get("group_by") or "category").strip().lower()
    q = (request.args.get("q") or "").strip()

    if group_by not in {"category", "vendor", "month"}:
        group_by = "category"

    year_options = get_budget_year_options_for_department(department_name)
    if not year and year_options:
        year = year_options[0]

    summary = get_budget_summary_for_department(
        department_name=department_name,
        year=year,
        q=q,
    )

    breakdown = get_budget_breakdown_for_department(
        department_name=department_name,
        year=year,
        group_by=group_by,
        q=q,
    )

    return render_template(
        "finance/budget.html",
        department_name=department_name,
        active_tab="budget",
        can_manage=can_manage_department(user_id, department_name),
        can_view_budget=has_budget_view(user_id),
        budget_summary=summary,
        budget_breakdown=breakdown,
        selected_year=year,
        year_options=year_options,
        selected_group_by=group_by,
        search_query=q,
    )