from flask import render_template, session

from apps.snipeops.blueprint import bp
from modules.core.auth.decorators import login_required, require_permission
from modules.core.settings.settings_service import get_setting, get_bool_setting


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