from flask import flash, redirect, render_template, request, url_for

from apps.snipeops.secure_user_rostering.service import (
    build_student_purge_preview,
    build_user_roster_preview,
    merge_snipe_users,
    purge_student_users,
)

from apps.snipeops.secure_user_rostering.blueprint import bp
from apps.snipeops.secure_user_rostering.mapping import get_default_user_field_mapping
from modules.core.auth.decorators import login_required, require_permission


@bp.route("/")
@login_required
@require_permission("snipeops.secure_user_rostering.view")
def user_roster():
    preview = None
    error = None

    if request.args.get("preview") == "1":
        try:
            preview = build_user_roster_preview()
            print("Secure User Rostering preview counts:", preview["counts"])
        except Exception as exc:
            error = str(exc)
            print("Secure User Rostering preview failed:", error)

    return render_template(
        "user_roster.html",
        preview=preview,
        error=error,
        field_mapping=get_default_user_field_mapping(),
    )


@bp.post("/student-purge/run")
@login_required
@require_permission("snipeops.secure_user_rostering.manage")
def run_student_purge():
    selected_user_ids = request.form.getlist("user_ids")
    confirmation = (request.form.get("confirmation") or "").strip()
    wants_json = request.headers.get("X-Requested-With") == "fetch"

    try:
        result = purge_student_users(
            user_ids=selected_user_ids,
            confirmation=confirmation,
            batch_limit=100,
        )

        if wants_json:
            return {
                "ok": not bool(result["errors"]),
                "result": result,
                "message": (
                    f"Student purge completed. Deleted: {len(result['deleted'])}. "
                    f"Skipped: {len(result['skipped'])}. Errors: {len(result['errors'])}."
                ),
            }

        flash(
            f"Student purge completed. Deleted: {len(result['deleted'])}. "
            f"Skipped: {len(result['skipped'])}. Errors: {len(result['errors'])}.",
            "success" if not result["errors"] else "warning",
        )

    except Exception as exc:
        if wants_json:
            return {
                "ok": False,
                "message": f"Student purge failed: {exc}",
            }, 400

        flash(f"Student purge failed: {exc}", "error")

    return redirect(url_for("secure_user_rostering.user_roster", _anchor="students"))


@bp.post("/merge-users/run")
@login_required
@require_permission("snipeops.secure_user_rostering.manage")
def run_merge_users():
    source_user_id = request.form.get("source_user_id")
    target_user_id = request.form.get("target_user_id")
    confirmation = (request.form.get("confirmation") or "").strip()
    delete_source = request.form.get("delete_source") == "1"
    wants_json = request.headers.get("X-Requested-With") == "fetch"

    try:
        result = merge_snipe_users(
            source_user_id=source_user_id,
            target_user_id=target_user_id,
            confirmation=confirmation,
            delete_source=delete_source,
        )

        message = (
            f"Merge completed. Moved {len(result['moved_assets'])} assets."
            if result["ok"]
            else f"Merge completed with errors. Moved {len(result['moved_assets'])} assets; errors: {len(result['errors'])}."
        )

        if wants_json:
            return {
                "ok": result["ok"],
                "result": result,
                "message": message,
            }

        flash(message, "success" if result["ok"] else "warning")

    except Exception as exc:
        if wants_json:
            return {
                "ok": False,
                "message": f"Merge failed: {exc}",
            }, 400

        flash(f"Merge failed: {exc}", "error")

    return redirect(url_for("secure_user_rostering.user_roster", _anchor="duplicates"))