from flask import render_template, session, request, redirect, url_for, flash
from apps.snipeops.sync_apply_service import apply_sync_action
from apps.snipeops.snipe_catalog.catalog_reader import get_models, get_locations, get_statuslabels

from apps.snipeops.blueprint import bp
from modules.core.auth.decorators import login_required, require_permission
from modules.core.settings.settings_service import get_setting, get_bool_setting

from apps.snipeops.connectors.intune_client import list_intune_devices
from apps.snipeops.connectors.mosyle_client import list_mosyle_devices
from apps.snipeops.sync_preview_service import build_sync_preview


def snipeops_available():
    enabled = get_bool_setting("snipeops.enabled", False)
    base_url = (get_setting("snipeops.base_url", "") or "").strip()
    api_token = (get_setting("snipeops.api_token", "") or "").strip()

    return enabled and bool(base_url and api_token)


def snipeops_admin_bypass_allowed():
    user_permissions = set(session.get("user_permissions", []))
    return "launchpad.settings.snipeops.manage" in user_permissions


@bp.route("/")
@login_required
@require_permission("snipeops.home.view")
def index():
    is_available = snipeops_available()
    admin_bypass = snipeops_admin_bypass_allowed()

    if not is_available and not admin_bypass:
        return render_template("snipeops/unavailable.html")

    return render_template(
        "snipeops/home.html",
        snipeops_integration_ready=is_available,
        snipeops_admin_bypass_active=(not is_available and admin_bypass),
    )


def intune_connector_status():
    enabled = get_bool_setting("integrations.microsoft.intune.enabled", False)
    tenant_id = (get_setting("integrations.microsoft.intune.tenant_id", "") or "").strip()
    client_id = (get_setting("integrations.microsoft.intune.client_id", "") or "").strip()
    client_secret = (get_setting("integrations.microsoft.intune.client_secret", "") or "").strip()

    return {
        "enabled": enabled,
        "configured": bool(enabled and tenant_id and client_id and client_secret),
        "tenant_id": tenant_id,
        "client_id": client_id,
    }


def mosyle_connector_status():
    enabled = get_bool_setting("integrations.mosyle.enabled", False)
    base_url = (get_setting("integrations.mosyle.base_url", "") or "").strip()
    username = (get_setting("integrations.mosyle.username", "") or "").strip()
    access_token = (get_setting("integrations.mosyle.access_token", "") or "").strip()

    return {
        "enabled": enabled,
        "configured": bool(enabled and base_url and access_token),
        "base_url": base_url,
        "username": username,
    }


@bp.route("/tools/intune-sync")
@login_required
@require_permission("snipeops.home.view")
def intune_sync():
    connector = intune_connector_status()
    preview = None
    error = None

    if request.args.get("preview") == "1":
        try:
            limit = int(request.args.get("limit", 25))
            limit = max(1, min(limit, 100))
            devices = list_intune_devices(limit=limit)
            preview = build_sync_preview(devices)
        except Exception as exc:
            error = str(exc)

    return render_template(
        "snipeops/tools/intune_sync.html",
        connector=connector,
        preview=preview,
        error=error,
        models=get_models(),
        locations=get_locations(),
        statuses=get_statuslabels(),
    )


@bp.route("/tools/mosyle-sync")
@login_required
@require_permission("snipeops.home.view")
def mosyle_sync():
    connector = mosyle_connector_status()
    preview = None
    error = None

    if request.args.get("preview") == "1":
        try:
            limit = int(request.args.get("limit", 25))
            limit = max(1, min(limit, 100))
            devices = list_mosyle_devices(limit=limit)
            preview = build_sync_preview(devices)
        except Exception as exc:
            error = str(exc)

    return render_template(
        "snipeops/tools/mosyle_sync.html",
        connector=connector,
        preview=preview,
        error=error,
        models=get_models(),
        locations=get_locations(),
        statuses=get_statuslabels(),
    )

@bp.post("/tools/apply-sync")
@login_required
@require_permission("snipeops.home.view")
def apply_sync():
    source = (request.form.get("source") or "intune").strip().lower()

    try:
        message = apply_sync_action(request.form)
        flash(message, "success")
    except Exception as exc:
        flash(f"Sync action failed: {exc}", "error")

    if source == "mosyle":
        return redirect(url_for("snipeops.mosyle_sync", preview=1))

    return redirect(url_for("snipeops.intune_sync", preview=1))