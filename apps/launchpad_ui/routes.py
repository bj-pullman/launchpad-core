import os

import requests
from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    jsonify,
    session,
)
from werkzeug.routing import BuildError

from . import launchpad_ui_bp
from .permissions import get_visible_settings_sections, get_visible_launchpad_apps
from modules.core.auth.decorators import login_required, require_permission
from modules.core.auth.user_admin_service import (
    list_local_users,
    get_local_user_by_user_id,
    create_local_user,
    create_sso_stub_user,
    update_local_user,
    set_local_user_password,
    replace_user_roles,
)
from modules.core.identity.rbac_service import (
    get_user_roles,
    list_roles,
    list_permissions,
    get_role_by_id,
    update_role,
    delete_role,
    replace_role_permissions,
    get_role_permission_keys,
    get_user_direct_permission_keys,
    replace_user_permissions,
    build_permission_catalog,
    build_user_access_summary,
)
from modules.core.identity.rbac_db import get_connection as get_rbac_connection
from modules.core.identity.user_service import get_user_by_id, update_user, create_user
from modules.core.settings.settings_service import get_setting, set_setting, get_bool_setting


def get_all_roles():
    with get_rbac_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM roles
            ORDER BY role_name
            """
        ).fetchall()

    return [dict(row) for row in rows]


def _user_permissions():
    return set(session.get("user_permissions", []))


def _require_manage_permission(permission_key: str, message: str):
    if permission_key not in _user_permissions():
        flash(message, "error")
        return False
    return True

def _truncate_text(value: str, max_length: int = 44) -> str:
    value = (value or "").strip()
    if len(value) <= max_length:
        return value

    truncated = value[: max_length - 3].rstrip(", ").rstrip()
    return f"{truncated}..."


def _group_permission_catalog():
    catalog = build_permission_catalog()
    grouped = {}

    for item in catalog:
        section = item["section"]
        group = item["group"]

        grouped.setdefault(section, {})
        grouped[section].setdefault(group, [])
        grouped[section][group].append(item)

    return grouped

def _to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _get_snipeops_settings():
    env_url = os.getenv("SNIPE_URL", "").strip()
    env_token = os.getenv("SNIPE_API_TOKEN", "").strip()
    env_verify_ssl = _to_bool(os.getenv("VERIFY_SSL", "true"), True)

    db_url = (get_setting("snipeops.base_url", "") or "").strip()
    db_token = (get_setting("snipeops.api_token", "") or "").strip()
    db_verify_ssl = get_setting("snipeops.verify_ssl", None)

    base_url = db_url or env_url
    api_token = db_token or env_token

    if db_verify_ssl is None:
        verify_ssl = env_verify_ssl
    else:
        verify_ssl = _to_bool(db_verify_ssl, True)

    token_source = "database" if db_token else ("env" if env_token else "none")

    return {
        "base_url": base_url,
        "api_token": api_token,
        "verify_ssl": verify_ssl,
        "has_api_token": bool(api_token),
        "token_source": token_source,
    }


def _test_snipeit_connection(base_url: str, api_token: str, verify_ssl: bool):
    if not base_url:
        return {
            "ok": False,
            "message": "Snipe-IT Base URL is required.",
        }

    if not api_token:
        return {
            "ok": False,
            "message": "A Snipe-IT API key is required.",
        }

    url = f"{base_url.rstrip('/')}/api/v1/statuslabels"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=10,
            verify=verify_ssl,
        )
    except requests.exceptions.SSLError:
        return {
            "ok": False,
            "message": "SSL verification failed while connecting to Snipe-IT.",
        }
    except requests.exceptions.ConnectTimeout:
        return {
            "ok": False,
            "message": "Connection to Snipe-IT timed out.",
        }
    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "message": "Could not reach the Snipe-IT server.",
        }
    except requests.exceptions.RequestException as exc:
        return {
            "ok": False,
            "message": f"Connection test failed: {exc}",
        }

    if response.status_code in (401, 403):
        return {
            "ok": False,
            "message": "Authentication failed. Check the API key.",
        }

    if not response.ok:
        return {
            "ok": False,
            "message": f"Snipe-IT returned HTTP {response.status_code}.",
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "message": "Snipe-IT returned a non-JSON response.",
        }

    total = payload.get("total")
    if total is not None:
        return {
            "ok": True,
            "message": f"Connection successful. Retrieved status labels successfully (total: {total}).",
        }

    return {
        "ok": True,
        "message": "Connection successful.",
    }


@launchpad_ui_bp.app_context_processor
def inject_launchpad_navigation():
    visible_apps = []

    for app in get_visible_launchpad_apps():
        try:
            url_for(app["endpoint"])
            visible_apps.append(app)
        except BuildError:
            current_app.logger.warning(
                "Skipping launchpad app with unregistered endpoint: %s",
                app["endpoint"],
            )

    return {
        "settings_sections": get_visible_settings_sections(),
        "launchpad_apps": visible_apps,
    }


@launchpad_ui_bp.route("/")
@login_required
def home():
    return render_template("launchpad_ui/home.html")


@launchpad_ui_bp.route("/settings")
@login_required
@require_permission("launchpad.settings.view")
def settings_index():
    return render_template("launchpad_ui/settings/index.html")


@launchpad_ui_bp.route("/settings/general", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.general.view")
def settings_general():
    timezone_options = [
        {"value": "America/Chicago", "label": "Central Time (America/Chicago)"},
        {"value": "America/Denver", "label": "Mountain Time (America/Denver)"},
        {"value": "America/New_York", "label": "Eastern Time (America/New_York)"},
        {"value": "America/Los_Angeles", "label": "Pacific Time (America/Los_Angeles)"},
        {"value": "America/Anchorage", "label": "Alaska Time (America/Anchorage)"},
        {"value": "Pacific/Honolulu", "label": "Hawaii Time (Pacific/Honolulu)"},
        {"value": "UTC", "label": "UTC"},
    ]

    language_options = [
        {"value": "en", "label": "English"},
        {"value": "es", "label": "Spanish"},
    ]

    date_format_options = [
        {"value": "mdy", "label": "MM/DD/YYYY"},
        {"value": "ymd", "label": "YYYY-MM-DD"},
        {"value": "dmy", "label": "DD/MM/YYYY"},
    ]

    time_format_options = [
        {"value": "12h", "label": "12-hour (2:30 PM)"},
        {"value": "24h", "label": "24-hour (14:30)"},
    ]

    valid_timezones = {item["value"] for item in timezone_options}
    valid_languages = {item["value"] for item in language_options}
    valid_date_formats = {item["value"] for item in date_format_options}
    valid_time_formats = {item["value"] for item in time_format_options}

    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.general.manage",
            "You do not have permission to update General settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_general"))

        organization_name = (request.form.get("organization_name") or "").strip()
        footer_text = (request.form.get("footer_text") or "").strip()
        support_email = (request.form.get("support_email") or "").strip()
        helpdesk_url = (request.form.get("helpdesk_url") or "").strip()
        announcement_enabled = 1 if request.form.get("announcement_enabled") == "1" else 0
        announcement_text = (request.form.get("announcement_text") or "").strip()

        timezone_value = (request.form.get("timezone") or "America/Chicago").strip()
        language_value = (request.form.get("language") or "en").strip()
        date_format_value = (request.form.get("date_format") or "mdy").strip()
        time_format_value = (request.form.get("time_format") or "12h").strip()

        if timezone_value not in valid_timezones:
            timezone_value = "America/Chicago"

        if language_value not in valid_languages:
            language_value = "en"

        if date_format_value not in valid_date_formats:
            date_format_value = "mdy"

        if time_format_value not in valid_time_formats:
            time_format_value = "12h"

        set_setting("general.organization_name", organization_name)
        set_setting("general.footer_text", footer_text)
        set_setting("general.support_email", support_email)
        set_setting("general.helpdesk_url", helpdesk_url)
        set_setting("general.announcement_enabled", announcement_enabled)
        set_setting("general.announcement_text", announcement_text)
        set_setting("general.timezone", timezone_value)
        set_setting("general.language", language_value)
        set_setting("general.date_format", date_format_value)
        set_setting("general.time_format", time_format_value)

        flash("General settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_general"))

    settings = {
        "organization_name": get_setting("general.organization_name", ""),
        "footer_text": get_setting("general.footer_text", "Sheridan School District • Internal Tech Ops"),
        "support_email": get_setting("general.support_email", ""),
        "helpdesk_url": get_setting("general.helpdesk_url", ""),
        "announcement_enabled": get_bool_setting("general.announcement_enabled", False),
        "announcement_text": get_setting("general.announcement_text", ""),
        "timezone": get_setting("general.timezone", "America/Chicago"),
        "language": get_setting("general.language", "en"),
        "date_format": get_setting("general.date_format", "mdy"),
        "time_format": get_setting("general.time_format", "12h"),
    }

    return render_template(
        "launchpad_ui/settings/general.html",
        active_section="general",
        settings=settings,
        timezone_options=timezone_options,
        language_options=language_options,
        date_format_options=date_format_options,
        time_format_options=time_format_options,
    )


@launchpad_ui_bp.route("/settings/snipeops", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.snipeops.view")
def settings_snipeops():
    current_settings = _get_snipeops_settings()

    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.snipeops.manage",
            "You do not have permission to update SnipeOps settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_snipeops"))

        base_url = (request.form.get("base_url") or "").strip()
        verify_ssl = 1 if request.form.get("verify_ssl") == "1" else 0
        new_api_token = (request.form.get("api_token") or "").strip()

        set_setting("snipeops.base_url", base_url)
        set_setting("snipeops.verify_ssl", verify_ssl)

        if new_api_token:
            set_setting("snipeops.api_token", new_api_token, is_sensitive=1)

        flash("SnipeOps settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_snipeops"))

    settings = {
        "base_url": current_settings["base_url"],
        "verify_ssl": current_settings["verify_ssl"],
        "has_api_token": current_settings["has_api_token"],
        "token_source": current_settings["token_source"],
    }

    return render_template(
        "launchpad_ui/settings/snipeops.html",
        active_section="snipeops",
        settings=settings,
    )


@launchpad_ui_bp.route("/settings/snipeops/test-connection", methods=["POST"])
@login_required
@require_permission("launchpad.settings.snipeops.view")
def settings_snipeops_test_connection():
    if "launchpad.settings.snipeops.manage" not in _user_permissions():
        return jsonify({
            "ok": False,
            "message": "You do not have permission to test the SnipeOps connection.",
        }), 403

    current_settings = _get_snipeops_settings()

    base_url = (request.form.get("base_url") or "").strip() or current_settings["base_url"]
    api_token = (request.form.get("api_token") or "").strip() or current_settings["api_token"]
    verify_ssl = _to_bool(request.form.get("verify_ssl"), current_settings["verify_ssl"])

    result = _test_snipeit_connection(base_url, api_token, verify_ssl)
    status_code = 200 if result["ok"] else 400
    return jsonify(result), status_code


@launchpad_ui_bp.route("/settings/saml")
@login_required
@require_permission("launchpad.settings.saml.view")
def settings_saml():
    return render_template("launchpad_ui/settings/saml.html", active_section="saml")


@launchpad_ui_bp.route("/settings/security")
@login_required
@require_permission("launchpad.settings.security.view")
def settings_security():
    return render_template("launchpad_ui/settings/security.html", active_section="security")


@launchpad_ui_bp.route("/settings/groups")
@login_required
@require_permission("launchpad.settings.groups.view")
def settings_groups():
    groups = list_roles(include_system=True)

    for group in groups:
        permission_keys = sorted(get_role_permission_keys(group["id"]))
        group["permission_count"] = len(permission_keys)
        group["permission_keys"] = permission_keys

    return render_template(
        "launchpad_ui/settings/groups.html",
        active_section="groups",
        groups=groups,
    )


@launchpad_ui_bp.route("/settings/groups/new", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.groups.manage")
def settings_groups_new():
    permission_catalog = _group_permission_catalog()

    if request.method == "POST":
        role_key = (request.form.get("role_key") or "").strip().lower().replace(" ", "_")
        role_name = (request.form.get("role_name") or "").strip()
        description = (request.form.get("description") or "").strip()
        selected_permissions = request.form.getlist("permissions")

        if not role_key:
            flash("Group key is required.", "error")
            return render_template(
                "launchpad_ui/settings/group_form.html",
                active_section="groups",
                form_mode="new",
                group={"role_key": "", "role_name": role_name, "description": description, "is_system": 0},
                selected_permissions=selected_permissions,
                permission_catalog=permission_catalog,
            )

        if not role_name:
            flash("Group name is required.", "error")
            return render_template(
                "launchpad_ui/settings/group_form.html",
                active_section="groups",
                form_mode="new",
                group={"role_key": role_key, "role_name": "", "description": description, "is_system": 0},
                selected_permissions=selected_permissions,
                permission_catalog=permission_catalog,
            )

        try:
            from modules.core.identity.rbac_service import create_role, get_role_by_key

            create_role(role_key, role_name, description, is_system=0)
            role = get_role_by_key(role_key)
            replace_role_permissions(role["id"], selected_permissions)

            flash("Group created successfully.", "success")
            return redirect(url_for("launchpad_ui.settings_groups"))
        except Exception as exc:
            current_app.logger.exception("Unable to create group")
            flash(f"Unable to create group: {exc}", "error")

        return render_template(
            "launchpad_ui/settings/group_form.html",
            active_section="groups",
            form_mode="new",
            group={"role_key": role_key, "role_name": role_name, "description": description, "is_system": 0},
            selected_permissions=selected_permissions,
            permission_catalog=permission_catalog,
        )

    return render_template(
        "launchpad_ui/settings/group_form.html",
        active_section="groups",
        form_mode="new",
        group={"role_key": "", "role_name": "", "description": "", "is_system": 0},
        selected_permissions=[],
        permission_catalog=permission_catalog,
    )


@launchpad_ui_bp.route("/settings/groups/<int:group_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.groups.manage")
def settings_groups_edit(group_id: int):
    group = get_role_by_id(group_id)
    if not group:
        flash("Group not found.", "error")
        return redirect(url_for("launchpad_ui.settings_groups"))

    permission_catalog = _group_permission_catalog()
    selected_permissions = sorted(get_role_permission_keys(group_id))

    if request.method == "POST":
        role_name = (request.form.get("role_name") or "").strip()
        description = (request.form.get("description") or "").strip()
        selected_permissions = request.form.getlist("permissions")

        if not role_name:
            flash("Group name is required.", "error")
            return render_template(
                "launchpad_ui/settings/group_form.html",
                active_section="groups",
                form_mode="edit",
                group={**group, "role_name": role_name, "description": description},
                selected_permissions=selected_permissions,
                permission_catalog=permission_catalog,
            )

        try:
            if int(group.get("is_system", 0)) == 0:
                update_role(group_id, role_name, description)

            replace_role_permissions(group_id, selected_permissions)

            flash("Group updated successfully.", "success")
            return redirect(url_for("launchpad_ui.settings_groups"))
        except Exception as exc:
            current_app.logger.exception("Unable to update group")
            flash(f"Unable to update group: {exc}", "error")

        return render_template(
            "launchpad_ui/settings/group_form.html",
            active_section="groups",
            form_mode="edit",
            group={**group, "role_name": role_name, "description": description},
            selected_permissions=selected_permissions,
            permission_catalog=permission_catalog,
        )

    return render_template(
        "launchpad_ui/settings/group_form.html",
        active_section="groups",
        form_mode="edit",
        group=group,
        selected_permissions=selected_permissions,
        permission_catalog=permission_catalog,
    )


@launchpad_ui_bp.route("/settings/groups/<int:group_id>/delete", methods=["POST"])
@login_required
@require_permission("launchpad.settings.groups.manage")
def settings_groups_delete(group_id: int):
    try:
        delete_role(group_id)
        flash("Group deleted successfully.", "success")
    except Exception as exc:
        flash(str(exc), "error")

    return redirect(url_for("launchpad_ui.settings_groups"))


@launchpad_ui_bp.route("/settings/users")
@login_required
@require_permission("launchpad.settings.users.view")
def settings_users():
    users = list_local_users()

    for user in users:
        groups = get_user_roles(user["user_id"])
        user["roles"] = groups

        group_names = [group["role_name"] for group in groups]
        user["groups_display_full"] = ", ".join(group_names) if group_names else "None"

        max_groups_shown = 2
        user["groups_display_badges"] = groups[:max_groups_shown]
        user["groups_display_remaining"] = max(0, len(groups) - max_groups_shown)

    return render_template(
        "launchpad_ui/settings/users.html",
        active_section="users",
        users=users,
    )


@launchpad_ui_bp.route("/settings/users/new", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.users.manage")
def settings_users_new():
    groups = list_roles(include_system=True)
    permission_catalog = _group_permission_catalog()

    if request.method == "POST":
        account_type = (request.form.get("account_type") or "local").strip().lower()
        username = (request.form.get("username") or "").strip().lower()
        display_name = (request.form.get("display_name") or "").strip()
        password = request.form.get("password") or ""
        is_active = 1 if request.form.get("is_active") == "1" else 0
        selected_group_keys = request.form.getlist("groups")
        selected_direct_permissions = request.form.getlist("direct_permissions")

        first_name = (request.form.get("first_name") or "").strip()
        last_name = (request.form.get("last_name") or "").strip()
        job_title = (request.form.get("job_title") or "").strip()
        department = (request.form.get("department") or "").strip()
        office_location = (request.form.get("office_location") or "").strip()
        company_name = (request.form.get("company_name") or "").strip()
        employee_id = (request.form.get("employee_id") or "").strip()
        preferred_language = (request.form.get("preferred_language") or "").strip()
        business_phone = (request.form.get("business_phone") or "").strip()
        mobile_phone = (request.form.get("mobile_phone") or "").strip()
        manager_email = (request.form.get("manager_email") or "").strip()
        manager_display_name = (request.form.get("manager_display_name") or "").strip()

        form_user = {
            "username": username,
            "display_name": display_name,
            "first_name": first_name,
            "last_name": last_name,
            "job_title": job_title,
            "department": department,
            "office_location": office_location,
            "company_name": company_name,
            "employee_id": employee_id,
            "preferred_language": preferred_language,
            "business_phone": business_phone,
            "mobile_phone": mobile_phone,
            "manager_email": manager_email,
            "manager_display_name": manager_display_name,
            "is_active": is_active,
        }

        if account_type not in {"local", "sso"}:
            account_type = "local"

        if not username:
            flash("Username or email is required.", "error")
            return render_template(
                "launchpad_ui/settings/users_form.html",
                active_section="users",
                user=form_user,
                groups=groups,
                selected_group_keys=selected_group_keys,
                selected_direct_permissions=selected_direct_permissions,
                permission_catalog=permission_catalog,
                access_summary=None,
                form_mode="new",
                account_type=account_type,
                display_name=display_name,
            )

        if not display_name:
            flash("Display name is required.", "error")
            return render_template(
                "launchpad_ui/settings/users_form.html",
                active_section="users",
                user=form_user,
                groups=groups,
                selected_group_keys=selected_group_keys,
                selected_direct_permissions=selected_direct_permissions,
                permission_catalog=permission_catalog,
                access_summary=None,
                form_mode="new",
                account_type=account_type,
                display_name=display_name,
            )

        if account_type == "sso" and "@" not in username:
            flash("SSO-only accounts must use an email address.", "error")
            return render_template(
                "launchpad_ui/settings/users_form.html",
                active_section="users",
                user=form_user,
                groups=groups,
                selected_group_keys=selected_group_keys,
                selected_direct_permissions=selected_direct_permissions,
                permission_catalog=permission_catalog,
                access_summary=None,
                form_mode="new",
                account_type=account_type,
                display_name=display_name,
            )

        if account_type == "local" and not password:
            flash("Password is required for local accounts.", "error")
            return render_template(
                "launchpad_ui/settings/users_form.html",
                active_section="users",
                user=form_user,
                groups=groups,
                selected_group_keys=selected_group_keys,
                selected_direct_permissions=selected_direct_permissions,
                permission_catalog=permission_catalog,
                access_summary=None,
                form_mode="new",
                account_type=account_type,
                display_name=display_name,
            )

        try:
            identity_user = create_user({
                "email": username,
                "username": username if account_type == "local" else None,
                "display_name": display_name,
                "is_active": is_active,
                "first_name": first_name,
                "last_name": last_name,
                "job_title": job_title,
                "department": department,
                "office_location": office_location,
                "company_name": company_name,
                "employee_id": employee_id,
                "preferred_language": preferred_language,
                "business_phone": business_phone,
                "mobile_phone": mobile_phone,
                "manager_email": manager_email,
                "manager_display_name": manager_display_name,
            })
            identity_user_id = identity_user["id"]

            if account_type == "local":
                create_local_user(
                    user_id=identity_user_id,
                    username=username,
                    password=password,
                    is_active=is_active,
                )
            else:
                create_sso_stub_user(
                    user_id=identity_user_id,
                    username=username,
                    is_active=is_active,
                )

            replace_user_roles(identity_user_id, selected_group_keys)
            replace_user_permissions(identity_user_id, selected_direct_permissions)

            flash("User created successfully.", "success")
            return redirect(url_for("launchpad_ui.settings_users"))

        except Exception as exc:
            current_app.logger.exception("Unable to create user")
            flash(f"Unable to create user: {exc}", "error")

        return render_template(
            "launchpad_ui/settings/users_form.html",
            active_section="users",
            user=form_user,
            groups=groups,
            selected_group_keys=selected_group_keys,
            selected_direct_permissions=selected_direct_permissions,
            permission_catalog=permission_catalog,
            access_summary=None,
            form_mode="new",
            account_type=account_type,
            display_name=display_name,
        )

    return render_template(
        "launchpad_ui/settings/users_form.html",
        active_section="users",
        user={},
        groups=groups,
        selected_group_keys=["viewer"],
        selected_direct_permissions=[],
        permission_catalog=permission_catalog,
        access_summary=None,
        form_mode="new",
        account_type="local",
        display_name="",
    )


@launchpad_ui_bp.route("/settings/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.users.manage")
def settings_users_edit(user_id: int):
    local_user = get_local_user_by_user_id(user_id)
    identity_user = get_user_by_id(user_id)

    if not local_user or not identity_user:
        flash("User not found.", "error")
        return redirect(url_for("launchpad_ui.settings_users"))

    user = {**identity_user, **local_user}

    groups = list_roles(include_system=True)
    permission_catalog = _group_permission_catalog()
    current_group_keys = [group["role_key"] for group in get_user_roles(user_id)]
    current_direct_permission_keys = sorted(get_user_direct_permission_keys(user_id))
    access_summary = build_user_access_summary(user_id)
    inherited_permissions = access_summary.get("inherited_permissions", [])
    direct_permissions = access_summary.get("direct_permissions", [])
    effective_permissions = access_summary.get("effective_permissions", [])

    if request.method == "POST":
        account_type = (request.form.get("account_type") or "local").strip().lower()
        username = (request.form.get("username") or "").strip().lower()
        display_name = (request.form.get("display_name") or "").strip()
        password = request.form.get("password") or ""
        is_active = 1 if request.form.get("is_active") == "1" else 0
        selected_group_keys = request.form.getlist("groups")
        selected_direct_permissions = request.form.getlist("direct_permissions")

        first_name = (request.form.get("first_name") or "").strip()
        last_name = (request.form.get("last_name") or "").strip()
        job_title = (request.form.get("job_title") or "").strip()
        department = (request.form.get("department") or "").strip()
        office_location = (request.form.get("office_location") or "").strip()
        company_name = (request.form.get("company_name") or "").strip()
        employee_id = (request.form.get("employee_id") or "").strip()
        preferred_language = (request.form.get("preferred_language") or "").strip()
        business_phone = (request.form.get("business_phone") or "").strip()
        mobile_phone = (request.form.get("mobile_phone") or "").strip()
        manager_email = (request.form.get("manager_email") or "").strip()
        manager_display_name = (request.form.get("manager_display_name") or "").strip()

        form_user = {
            **user,
            "username": username,
            "display_name": display_name,
            "first_name": first_name,
            "last_name": last_name,
            "job_title": job_title,
            "department": department,
            "office_location": office_location,
            "company_name": company_name,
            "employee_id": employee_id,
            "preferred_language": preferred_language,
            "business_phone": business_phone,
            "mobile_phone": mobile_phone,
            "manager_email": manager_email,
            "manager_display_name": manager_display_name,
            "is_active": is_active,
        }

        if account_type not in {"local", "sso"}:
            account_type = "local"

        if not username:
            flash("Username or email is required.", "error")
            return render_template(
                "launchpad_ui/settings/users_form.html",
                active_section="users",
                user=form_user,
                groups=groups,
                selected_group_keys=selected_group_keys,
                selected_direct_permissions=selected_direct_permissions,
                permission_catalog=permission_catalog,
                access_summary=build_user_access_summary(user_id),
                form_mode="edit",
                account_type=account_type,
                display_name=display_name,
            )

        if not display_name:
            flash("Display name is required.", "error")
            return render_template(
                "launchpad_ui/settings/users_form.html",
                active_section="users",
                user=form_user,
                groups=groups,
                selected_group_keys=selected_group_keys,
                selected_direct_permissions=selected_direct_permissions,
                permission_catalog=permission_catalog,
                access_summary=build_user_access_summary(user_id),
                form_mode="edit",
                account_type=account_type,
                display_name=display_name,
            )

        if account_type == "sso" and "@" not in username:
            flash("SSO-only accounts must use an email address.", "error")
            return render_template(
                "launchpad_ui/settings/users_form.html",
                active_section="users",
                user=form_user,
                groups=groups,
                selected_group_keys=selected_group_keys,
                selected_direct_permissions=selected_direct_permissions,
                permission_catalog=permission_catalog,
                access_summary=build_user_access_summary(user_id),
                form_mode="edit",
                account_type=account_type,
                display_name=display_name,
            )

        update_user(user_id, {
            "email": username,
            "username": username if account_type == "local" else None,
            "display_name": display_name,
            "is_active": is_active,
            "first_name": first_name,
            "last_name": last_name,
            "job_title": job_title,
            "department": department,
            "office_location": office_location,
            "company_name": company_name,
            "employee_id": employee_id,
            "preferred_language": preferred_language,
            "business_phone": business_phone,
            "mobile_phone": mobile_phone,
            "manager_email": manager_email,
            "manager_display_name": manager_display_name,
        })

        update_local_user(user_id, username, is_active)

        if password.strip():
            set_local_user_password(user_id, password)

        replace_user_roles(user_id, selected_group_keys)
        replace_user_permissions(user_id, selected_direct_permissions)

        flash("User updated successfully.", "success")
        return redirect(url_for("launchpad_ui.settings_users_edit", user_id=user_id))

    account_type = "local" if user.get("password_hash") else "sso"

    return render_template(
        "launchpad_ui/settings/users_form.html",
        active_section="users",
        user=user,
        groups=groups,
        selected_group_keys=current_group_keys,
        selected_direct_permissions=current_direct_permission_keys,
        permission_catalog=permission_catalog,
        access_summary=access_summary,
        form_mode="edit",
        account_type=account_type,
        display_name=user.get("display_name", ""),
        inherited_permissions = access_summary.get("inherited_permissions", []),
        direct_permissions = access_summary.get("direct_permissions", []),
        effective_permissions = access_summary.get("effective_permissions", []),
    )