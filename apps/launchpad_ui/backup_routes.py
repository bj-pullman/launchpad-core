from flask import flash, render_template, request

from . import launchpad_ui_bp
from .backup_service import (
    apply_update,
    generate_backup,
    get_backup_root,
    get_update_status,
    import_existing_backups,
    list_backups,
)
from .service import user_permissions
from modules.core.auth.decorators import login_required, require_permission

from .maintenance_job_service import (
    get_cached_update_status,
    get_latest_job,
    start_update_check_job,
    start_apply_update_job,
)


VALID_TABS = {"backups", "updates", "rollback"}


def _active_tab(default="backups"):
    tab = (request.args.get("tab") or default).strip().lower()
    return tab if tab in VALID_TABS else default


def _render_system_maintenance(
    *,
    active_tab="backups",
    backups=None,
    update_status=None,
    update_job=None,
):
    return render_template(
        "launchpad_ui/settings/backups.html",
        active_section="backups",
        active_tab=active_tab,
        backups=backups,
        backup_root=str(get_backup_root()),
        update_status=update_status,
        update_job=update_job,
        can_manage_backups="launchpad.settings.backups.manage" in user_permissions(),
    )


@launchpad_ui_bp.route("/settings/backups", methods=["GET"])
@login_required
@require_permission("launchpad.settings.backups.view")
def settings_backups():
    active_tab = _active_tab()

    backups = None
    update_status = None
    update_job = None

    if active_tab in {"backups", "rollback"}:
        backups = list_backups(limit=20)

    if active_tab == "updates":
        update_status = get_cached_update_status()
        update_job = get_latest_job("check_update")

    return _render_system_maintenance(
        active_tab=active_tab,
        backups=backups,
        update_status=update_status,
        update_job=update_job,
    )


@launchpad_ui_bp.route("/settings/backups/import-existing", methods=["POST"])
@login_required
@require_permission("launchpad.settings.backups.manage")
def settings_backups_import_existing():
    result = import_existing_backups(limit=200)

    if result.get("ok"):
        flash(
            f"Backup database refreshed. Imported {result.get('imported', 0)} backup records.",
            "success",
        )
    else:
        flash(
            "Backup database refreshed with issues: "
            + " ".join(result.get("errors") or []),
            "warning",
        )

    return _render_system_maintenance(
        active_tab="backups",
        backups=list_backups(limit=20),
        update_status=None,
    )


@launchpad_ui_bp.route("/settings/backups/generate", methods=["POST"])
@login_required
@require_permission("launchpad.settings.backups.manage")
def settings_backups_generate():
    reason = (request.form.get("reason") or "manual").strip()
    include_app_snapshot = request.form.get("include_app_snapshot") == "1"

    result = generate_backup(
        reason=reason,
        include_app_snapshot=include_app_snapshot,
    )

    if result.get("ok"):
        flash("Backup generated successfully.", "success")
    else:
        errors = result.get("errors") or [result.get("error") or "Unknown backup error."]
        flash("Backup failed: " + " ".join(str(error) for error in errors if error), "error")

    return _render_system_maintenance(
        active_tab="backups",
        backups=list_backups(limit=20),
        update_status=None,
    )


@launchpad_ui_bp.route("/settings/backups/check-update", methods=["POST"])
@login_required
@require_permission("launchpad.settings.backups.view")
def settings_backups_check_update():
    job = start_update_check_job()
    flash("Update check started. Refresh this page in a few seconds to view the result.", "info")

    return _render_system_maintenance(
        active_tab="updates",
        backups=None,
        update_status=get_cached_update_status(),
        update_job=job,
    )


@launchpad_ui_bp.route("/settings/backups/apply-update", methods=["POST"])
@login_required
@require_permission("launchpad.settings.backups.manage")
def settings_backups_apply_update():
    job = start_apply_update_job()
    flash("Update started. The app may restart during the update. Refresh this page after it comes back online.", "info")

    return _render_system_maintenance(
        active_tab="updates",
        backups=None,
        update_status=get_cached_update_status(),
        update_job=job,
    )


@launchpad_ui_bp.route("/settings/backups/rollback-options", methods=["POST"])
@login_required
@require_permission("launchpad.settings.backups.view")
def settings_backups_rollback_options():
    return _render_system_maintenance(
        active_tab="rollback",
        backups=list_backups(limit=20),
        update_status=None,
    )