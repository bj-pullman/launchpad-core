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
from .service import (
    user_permissions,
    to_bool,
    get_snipeops_settings,
    test_snipeit_connection,
    authentication_policy_settings,
    microsoft_integration_settings,
    google_integration_settings,
    saml_integration_settings,
    test_oidc_configuration,
    test_saml_configuration,
    group_permission_catalog,
    save_finance_notification_logo,
    build_finance_template_preview_context,
    render_finance_template_tokens,
    finance_notification_settings,
    build_finance_preview_lines,
    mosyle_integration_settings,
)

from apps.staff_status.service import (
    get_department_record,
    list_active_departments_from_users,
    upsert_department_settings,
    build_public_url as build_staff_status_public_url,
)

from apps.staff_status.access_service import (
    grant_department_access,
    revoke_department_access,
    list_staff_status_access_with_users,
)

from apps.finance.notification_service import send_finance_test_email

from apps.snipeops.mapping_service import (
    list_mappings,
    upsert_mapping,
    delete_mapping,
)

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
    get_role_by_id,
    update_role,
    delete_role,
    replace_role_permissions,
    get_role_permission_keys,
    get_user_direct_permission_keys,
    replace_user_permissions,
    build_user_access_summary,
)

from modules.core.identity.user_service import (
    get_user_by_id,
    update_user,
    create_user,
    list_users,
    update_user_theme_preference,
)

from modules.core.settings.settings_service import get_setting, set_setting, get_bool_setting

from modules.core.api_keys.service import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
    delete_api_key,
)

from tasks.scheduler import configure_jobs


def _require_manage_permission(permission_key: str, message: str):
    if permission_key not in user_permissions():
        flash(message, "error")
        return False
    return True


@launchpad_ui_bp.app_context_processor
def inject_launchpad_navigation():
    visible_apps = []

    for app in get_visible_launchpad_apps():
        try:
            url_for(app["endpoint"])
            visible_apps.append(app)
        except BuildError:
            current_app.logger.debug(
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
    setup_completed = get_bool_setting("setup.completed", False)

    setup_status = {
        "organization_completed": get_bool_setting("setup.organization.completed", False),
        "organization_skipped": get_bool_setting("setup.organization.skipped", False),
        "email_completed": get_bool_setting("setup.email.completed", False),
        "email_skipped": get_bool_setting("setup.email.skipped", False),
        "authentication_completed": get_bool_setting("setup.authentication.completed", False),
        "authentication_skipped": get_bool_setting("setup.authentication.skipped", False),
        "users_completed": get_bool_setting("setup.users.completed", False),
        "users_skipped": get_bool_setting("setup.users.skipped", False),
        "apps_completed": get_bool_setting("setup.apps.completed", False),
        "apps_skipped": get_bool_setting("setup.apps.skipped", False),
    }

    setup_total_steps = 5
    setup_completed_steps = sum(
        1
        for key, value in setup_status.items()
        if key.endswith("_completed") and value
    )
    setup_skipped_steps = sum(
        1
        for key, value in setup_status.items()
        if key.endswith("_skipped") and value
    )

    return render_template(
        "launchpad_ui/home.html",
        setup_completed=setup_completed,
        setup_status=setup_status,
        setup_total_steps=setup_total_steps,
        setup_completed_steps=setup_completed_steps,
        setup_skipped_steps=setup_skipped_steps,
    )


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
        public_base_url = (request.form.get("public_base_url") or "").strip().rstrip("/")
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
        set_setting("general.public_base_url", public_base_url)
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
        "public_base_url": get_setting("general.public_base_url", ""),
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
    active_tab = (
        request.form.get("active_tab")
        or request.args.get("tab")
        or "general"
    ).strip().lower()

    if active_tab not in {"general", "mappings"}:
        active_tab = "general"

    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.snipeops.manage",
            "You do not have permission to update SnipeOps settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_snipeops", tab=active_tab))

        action = (request.form.get("action") or "").strip().lower()

        if action == "save_mapping":
            source = (request.form.get("source") or "any").strip()
            field = (request.form.get("field") or "").strip()
            raw_value = (request.form.get("raw_value") or "").strip()
            mapped_value = (request.form.get("mapped_value") or "").strip()
            notes = (request.form.get("notes") or "").strip()

            try:
                upsert_mapping(
                    source=source,
                    field=field,
                    raw_value=raw_value,
                    mapped_value=mapped_value,
                    notes=notes,
                )
                flash("Mapping saved.", "success")
            except ValueError as exc:
                flash(str(exc), "error")

            return redirect(url_for("launchpad_ui.settings_snipeops", tab="mappings"))

        flash("Unsupported SnipeOps settings action.", "error")
        return redirect(url_for("launchpad_ui.settings_snipeops", tab=active_tab))

    selected_field = (request.args.get("field") or "").strip()
    selected_source = (request.args.get("source") or "").strip()

    mappings = list_mappings(
        field=selected_field or None,
        source=selected_source or None,
    )

    return render_template(
        "launchpad_ui/settings/snipeops.html",
        active_section="snipeops",
        active_tab=active_tab,
        mappings=mappings,
        selected_field=selected_field,
        selected_source=selected_source,
        source_options=[
            {"value": "", "label": "All Sources"},
            {"value": "any", "label": "Any"},
            {"value": "intune", "label": "Intune"},
            {"value": "mosyle", "label": "Mosyle"},
        ],
        field_options=[
            {"value": "", "label": "All Fields"},
            {"value": "model", "label": "Model"},
            {"value": "manufacturer", "label": "Manufacturer"},
            {"value": "os_version", "label": "OS Version"},
            {"value": "device_type", "label": "Device Type"},
        ],
    )


@launchpad_ui_bp.route("/settings/snipeops/test-connection", methods=["POST"])
@login_required
@require_permission("launchpad.settings.snipeops.view")
def settings_snipeops_test_connection():
    if "launchpad.settings.snipeops.manage" not in user_permissions():
        return jsonify({
            "ok": False,
            "message": "You do not have permission to test the SnipeOps connection.",
        }), 403

    current_settings = get_snipeops_settings()

    base_url = (request.form.get("base_url") or "").strip() or current_settings["base_url"]
    api_token = (request.form.get("api_token") or "").strip() or current_settings["api_token"]
    verify_ssl = to_bool(request.form.get("verify_ssl"), current_settings["verify_ssl"])

    result = test_snipeit_connection(base_url, api_token, verify_ssl)
    status_code = 200 if result["ok"] else 400
    return jsonify(result), status_code


@launchpad_ui_bp.route("/settings/snipeops/mappings")
@login_required
@require_permission("launchpad.settings.snipeops.view")
def settings_snipeops_mappings():
    return redirect(url_for("launchpad_ui.settings_snipeops", tab="mappings"))


@launchpad_ui_bp.route("/settings/snipeops/mappings/<int:mapping_id>/delete", methods=["POST"])
@login_required
@require_permission("launchpad.settings.snipeops.manage")
def delete_snipeops_mapping(mapping_id):
    delete_mapping(mapping_id)
    flash("Mapping deleted.", "success")
    return redirect(url_for("launchpad_ui.settings_snipeops", tab="mappings"))


@launchpad_ui_bp.route("/settings/authentication", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.saml.view")
def settings_authentication():
    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.saml.manage",
            "You do not have permission to update Authentication settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_authentication"))

        set_setting("auth.local.enabled", 1 if request.form.get("local_enabled") == "1" else 0)
        set_setting("auth.local.mode", (request.form.get("local_mode") or "breakglass_only").strip())
        set_setting(
            "auth.local.hide_form_when_restricted",
            1 if request.form.get("local_hide_form_when_restricted") == "1" else 0,
        )

        set_setting("auth.primary_method", (request.form.get("primary_method") or "local").strip())
        set_setting(
            "auth.access.require_local_user_for_sso",
            1 if request.form.get("require_local_user_for_sso") == "1" else 0,
        )
        set_setting("auth.access.match_user_by", (request.form.get("match_user_by") or "email").strip())
        set_setting(
            "auth.access.deny_if_user_not_found",
            1 if request.form.get("deny_if_user_not_found") == "1" else 0,
        )
        set_setting(
            "auth.access.deny_if_inactive",
            1 if request.form.get("deny_if_inactive") == "1" else 0,
        )
        set_setting("auth.access.allowed_domains", (request.form.get("allowed_domains") or "").strip())
        set_setting("auth.access.required_groups", (request.form.get("required_groups") or "").strip())
        set_setting(
            "auth.access.required_groups_mode",
            (request.form.get("required_groups_mode") or "any").strip(),
        )
        set_setting(
            "auth.access.allow_breakglass_with_sso",
            1 if request.form.get("allow_breakglass_with_sso") == "1" else 0,
        )

        flash("Authentication settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_authentication"))

    settings = authentication_policy_settings()

    return render_template(
        "launchpad_ui/settings/authentication.html",
        active_section="authentication",
        settings=settings,
    )


@launchpad_ui_bp.route("/settings/authentication/test-connection", methods=["POST"])
@login_required
@require_permission("launchpad.settings.saml.view")
def settings_authentication_test_connection():
    if "launchpad.settings.saml.manage" not in user_permissions():
        return jsonify({
            "ok": False,
            "message": "You do not have permission to test authentication settings.",
        }), 403

    provider = (request.form.get("provider") or "").strip().lower()

    if provider == "microsoft_oidc":
        result = test_oidc_configuration("microsoft_oidc", request.form)
    elif provider == "google_oidc":
        result = test_oidc_configuration("google_oidc", request.form)
    elif provider == "saml":
        result = test_saml_configuration(request.form)
    else:
        result = {"ok": False, "message": "Unsupported provider."}

    status_code = 200 if result["ok"] else 400
    return jsonify(result), status_code


@launchpad_ui_bp.route("/settings/saml")
@login_required
@require_permission("launchpad.settings.saml.view")
def settings_saml():
    return redirect(url_for("launchpad_ui.settings_authentication"))


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
    permission_catalog = group_permission_catalog()

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

    permission_catalog = group_permission_catalog()
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
        identity_user = get_user_by_id(user["user_id"]) or {}

        user["email"] = identity_user.get("email") or user.get("email")
        user["display_name"] = identity_user.get("display_name") or user.get("display_name")
        user["first_name"] = identity_user.get("first_name")
        user["last_name"] = identity_user.get("last_name")
        user["job_title"] = identity_user.get("job_title")
        user["department"] = identity_user.get("department")
        user["office_location"] = identity_user.get("office_location")

        user["sick_allowance_days"] = identity_user.get("sick_allowance_days", 12)
        user["personal_allowance_days"] = identity_user.get("personal_allowance_days", 3)
        user["vacation_allowance_days"] = identity_user.get("vacation_allowance_days", 10)
        user["other_allowance_days"] = identity_user.get("other_allowance_days", 0)

        groups = get_user_roles(user["user_id"])
        user["roles"] = groups

        group_names = [group["role_name"] for group in groups]
        user["groups_display_full"] = ", ".join(group_names) if group_names else "None"

        max_groups_shown = 2
        user["groups_display_badges"] = groups[:max_groups_shown]
        user["groups_display_remaining"] = max(0, len(groups) - max_groups_shown)

    departments = sorted({
        (user.get("department") or "").strip()
        for user in users
        if (user.get("department") or "").strip()
    })

    return render_template(
        "launchpad_ui/settings/users.html",
        active_section="users",
        users=users,
        departments=departments,
    )


@launchpad_ui_bp.route("/settings/users/new", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.users.manage")
def settings_users_new():
    groups = list_roles(include_system=True)
    permission_catalog = group_permission_catalog()

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
    permission_catalog = group_permission_catalog()
    current_group_keys = [group["role_key"] for group in get_user_roles(user_id)]
    current_direct_permission_keys = sorted(get_user_direct_permission_keys(user_id))
    access_summary = build_user_access_summary(user_id)

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
        return redirect(url_for("launchpad_ui.settings_users"))

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
        inherited_permissions=access_summary.get("inherited_permissions", []),
        direct_permissions=access_summary.get("direct_permissions", []),
        effective_permissions=access_summary.get("effective_permissions", []),
    )


@launchpad_ui_bp.route("/settings/users/<int:user_id>/delete", methods=["POST"])
@login_required
@require_permission("launchpad.settings.users.manage")
def settings_users_delete(user_id: int):
    from modules.core.identity.user_service import delete_user

    try:
        ok = delete_user(user_id)
        if ok:
            flash("User deleted successfully.", "success")
        else:
            flash("User not found.", "error")
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception:
        flash("Unable to delete user.", "error")

    return redirect(url_for("launchpad_ui.settings_users"))


@launchpad_ui_bp.route("/settings/users/bulk-action", methods=["POST"])
@login_required
@require_permission("launchpad.settings.users.manage")
def settings_users_bulk_action():
    payload = request.get_json(silent=True) or {}

    action = (payload.get("action") or "").strip().lower()
    raw_user_ids = payload.get("user_ids") or []

    user_ids = []
    for raw_user_id in raw_user_ids:
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            continue

        if user_id > 0:
            user_ids.append(user_id)

    user_ids = list(dict.fromkeys(user_ids))

    if not action:
        return jsonify({"ok": False, "message": "Bulk action is required."}), 400

    if not user_ids:
        return jsonify({"ok": False, "message": "At least one user must be selected."}), 400

    if action not in {"activate", "disable"}:
        return jsonify({"ok": False, "message": "Unsupported bulk action."}), 400

    updated_count = 0
    skipped_count = 0
    errors = []

    for user_id in user_ids:
        local_user = get_local_user_by_user_id(user_id)
        identity_user = get_user_by_id(user_id)

        if not local_user or not identity_user:
            skipped_count += 1
            continue

        username = (
            local_user.get("username")
            or identity_user.get("email")
            or identity_user.get("username")
            or ""
        ).strip().lower()

        if not username:
            skipped_count += 1
            errors.append(f"User {user_id} has no username or email.")
            continue

        try:
            update_user(user_id, {
                "email": identity_user.get("email"),
                "username": identity_user.get("username"),
                "display_name": identity_user.get("display_name"),
                "is_active": 1 if action == "activate" else 0,
                "first_name": identity_user.get("first_name"),
                "last_name": identity_user.get("last_name"),
                "job_title": identity_user.get("job_title"),
                "department": identity_user.get("department"),
                "office_location": identity_user.get("office_location"),
                "company_name": identity_user.get("company_name"),
                "employee_id": identity_user.get("employee_id"),
                "preferred_language": identity_user.get("preferred_language"),
                "business_phone": identity_user.get("business_phone"),
                "mobile_phone": identity_user.get("mobile_phone"),
                "manager_email": identity_user.get("manager_email"),
                "manager_display_name": identity_user.get("manager_display_name"),
            })

            update_local_user(user_id, username, 1 if action == "activate" else 0)
            updated_count += 1

        except Exception as exc:
            skipped_count += 1
            current_app.logger.exception("Unable to bulk update user_id=%s", user_id)
            errors.append(f"User {user_id}: {exc}")

    return jsonify({
        "ok": True,
        "action": action,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "errors": errors,
        "message": f"{'Activated' if action == 'activate' else 'Disabled'} {updated_count} user(s).",
    })


@launchpad_ui_bp.route("/settings/staff-status", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.staff_status.view")
def settings_staff_status():
    available_departments = list_active_departments_from_users()

    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.staff_status.manage",
            "You do not have permission to update Staff Status settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_staff_status"))

        action = (request.form.get("action") or "save_settings").strip().lower()

        if action == "add_department_operator":
            user_id = request.form.get("department_operator_user_id", type=int)
            department_names = [
                item.strip()
                for item in request.form.getlist("department_operator_department_names")
                if item.strip()
            ]

            if not user_id:
                flash("A user must be selected.", "error")
                return redirect(url_for("launchpad_ui.settings_staff_status"))

            if not department_names:
                flash("At least one department must be selected.", "error")
                return redirect(url_for("launchpad_ui.settings_staff_status"))

            try:
                for department_name in department_names:
                    grant_department_access(user_id, department_name)
                flash("Department operator assignment(s) added.", "success")
            except Exception as exc:
                flash(f"Unable to add department operator assignment(s): {exc}", "error")

            return redirect(url_for("launchpad_ui.settings_staff_status"))

        if action == "remove_department_operator":
            user_id = request.form.get("department_operator_user_id", type=int)
            department_name = (request.form.get("department_operator_department_name") or "").strip()

            if not user_id or not department_name:
                flash("A valid assignment is required.", "error")
                return redirect(url_for("launchpad_ui.settings_staff_status"))

            try:
                revoke_department_access(user_id, department_name)
                flash("Department operator assignment removed.", "success")
            except Exception as exc:
                flash(f"Unable to remove department operator assignment: {exc}", "error")

            return redirect(url_for("launchpad_ui.settings_staff_status"))

        enabled_departments = request.form.getlist("enabled_departments")
        daily_reset_enabled = 1 if request.form.get("daily_reset_enabled") == "1" else 0
        daily_reset_time = (request.form.get("daily_reset_time") or "01:00").strip()
        board_refresh_seconds = (request.form.get("board_refresh_seconds") or "15").strip()

        set_setting("staff_status.enabled_departments", ",".join(enabled_departments))
        set_setting("staff_status.daily_reset_enabled", daily_reset_enabled)
        set_setting("staff_status.daily_reset_time", daily_reset_time)
        set_setting("staff_status.board_refresh_seconds", board_refresh_seconds)

        for department_name in available_departments:
            is_enabled = department_name in enabled_departments
            home_location = (request.form.get(f"home_location_{department_name}") or "").strip()

            set_setting(
                f"staff_status.department.{department_name}.home_location",
                home_location,
            )

            upsert_department_settings(
                department_name=department_name,
                is_enabled=is_enabled,
                home_location=home_location,
            )

        configure_jobs()
        flash("Staff Status settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_staff_status"))

    enabled_departments_raw = get_setting("staff_status.enabled_departments", "") or ""
    enabled_departments = [
        item.strip() for item in enabled_departments_raw.split(",") if item.strip()
    ]

    department_rows = []
    for department_name in available_departments:
        department_record = get_department_record(department_name)
        kiosk_token = department_record.get("kiosk_token") if department_record else None
        board_token = department_record.get("board_token") if department_record else None
        kiosk_enabled = (
            int(department_record.get("kiosk_enabled", 0)) == 1
            if department_record
            else False
        )
        home_location = get_setting(
            f"staff_status.department.{department_name}.home_location",
            department_record.get("home_location_label", "") if department_record else "",
        )

        department_rows.append({
            "department_name": department_name,
            "is_enabled": department_name in enabled_departments,
            "home_location": home_location or "",
            "kiosk_enabled": kiosk_enabled,
            "kiosk_token": kiosk_token,
            "board_token": board_token,
            "kiosk_url": (
                build_staff_status_public_url("staff_status.kiosk", token=kiosk_token)
                if kiosk_enabled and kiosk_token
                else ""
            ),
            "board_url": (
                build_staff_status_public_url("staff_status.board_public", token=board_token)
                if board_token
                else ""
            ),
        })

    settings = {
        "enabled_departments": enabled_departments,
        "daily_reset_enabled": get_bool_setting("staff_status.daily_reset_enabled", True),
        "daily_reset_time": get_setting("staff_status.daily_reset_time", "01:00"),
        "board_refresh_seconds": get_setting("staff_status.board_refresh_seconds", "15"),
    }

    return render_template(
        "launchpad_ui/settings/staff_status.html",
        active_section="staff_status",
        settings=settings,
        department_rows=department_rows,
        department_operator_assignments=list_staff_status_access_with_users(),
        assignable_users=list_users(active_only=True),
    )


@launchpad_ui_bp.route("/settings/integrations")
@login_required
@require_permission("launchpad.settings.view")
def settings_integrations():
    perms = user_permissions()

    return render_template(
        "launchpad_ui/settings/integrations.html",
        active_section="integrations",
        can_view_microsoft="launchpad.settings.saml.view" in perms,
        can_view_google="launchpad.settings.saml.view" in perms,
        can_view_saml="launchpad.settings.saml.view" in perms,
        can_view_snipeit="launchpad.settings.snipeops.view" in perms,
        can_view_email="launchpad.settings.view" in perms,
    )


@launchpad_ui_bp.route("/settings/integrations/microsoft", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.saml.view")
def settings_integrations_microsoft():
    active_tab = (
        request.form.get("active_tab")
        or request.args.get("tab")
        or "signin"
    ).strip().lower()

    if active_tab not in {"signin", "intune"}:
        active_tab = "signin"

    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.saml.manage",
            "You do not have permission to update Microsoft integration settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_integrations_microsoft", tab=active_tab))

        action = (request.form.get("action") or "save").strip().lower()

        if action == "save_oidc":
            set_setting(
                "auth.microsoft_oidc.enabled",
                1 if request.form.get("microsoft_oidc_enabled") == "1" else 0,
            )
            set_setting(
                "auth.microsoft_oidc.client_id",
                (request.form.get("microsoft_client_id") or "").strip(),
            )

            microsoft_secret = (request.form.get("microsoft_client_secret") or "").strip()
            if microsoft_secret:
                set_setting("auth.microsoft_oidc.client_secret", microsoft_secret, is_sensitive=1)

            set_setting(
                "auth.microsoft_oidc.tenant_id",
                (request.form.get("microsoft_tenant_id") or "common").strip(),
            )
            set_setting(
                "auth.microsoft_oidc.redirect_uri",
                (request.form.get("microsoft_redirect_uri") or "").strip(),
            )

            flash("Microsoft sign-in settings saved.", "success")
            return redirect(url_for("launchpad_ui.settings_integrations_microsoft", tab=active_tab))

        if action == "save_intune":
            set_setting(
                "integrations.microsoft.intune.enabled",
                1 if request.form.get("intune_enabled") == "1" else 0,
            )
            set_setting(
                "integrations.microsoft.intune.tenant_id",
                (request.form.get("intune_tenant_id") or "").strip(),
            )
            set_setting(
                "integrations.microsoft.intune.client_id",
                (request.form.get("intune_client_id") or "").strip(),
            )

            intune_client_secret = (request.form.get("intune_client_secret") or "").strip()
            if intune_client_secret:
                set_setting(
                    "integrations.microsoft.intune.client_secret",
                    intune_client_secret,
                    is_sensitive=1,
                )

            graph_base_url = (
                request.form.get("intune_graph_base_url")
                or "https://graph.microsoft.com/v1.0"
            ).strip().rstrip("/")

            set_setting(
                "integrations.microsoft.intune.graph_base_url",
                graph_base_url,
            )

            flash("Microsoft Intune settings saved.", "success")
            return redirect(url_for("launchpad_ui.settings_integrations_microsoft", tab="intune"))

        flash("Unsupported Microsoft integration action.", "error")
        return redirect(url_for("launchpad_ui.settings_integrations_microsoft", tab=active_tab))

    return render_template(
        "launchpad_ui/settings/integrations_microsoft.html",
        active_section="integrations",
        active_tab=active_tab,
        settings=microsoft_integration_settings(),
    )


@launchpad_ui_bp.route("/settings/integrations/google", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.saml.view")
def settings_integrations_google():
    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.saml.manage",
            "You do not have permission to update Google integration settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_integrations_google"))

        set_setting("auth.google_oidc.enabled", 1 if request.form.get("google_oidc_enabled") == "1" else 0)
        set_setting("auth.google_oidc.client_id", (request.form.get("google_client_id") or "").strip())

        google_secret = (request.form.get("google_client_secret") or "").strip()
        if google_secret:
            set_setting("auth.google_oidc.client_secret", google_secret, is_sensitive=1)

        set_setting("auth.google_oidc.hosted_domain", (request.form.get("google_hosted_domain") or "").strip())
        set_setting("auth.google_oidc.redirect_uri", (request.form.get("google_redirect_uri") or "").strip())

        flash("Google integration settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_integrations_google"))

    return render_template(
        "launchpad_ui/settings/integrations_google.html",
        active_section="integrations",
        settings=google_integration_settings(),
    )


@launchpad_ui_bp.route("/settings/integrations/saml", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.saml.view")
def settings_integrations_saml():
    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.saml.manage",
            "You do not have permission to update SAML integration settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_integrations_saml"))

        uploaded_metadata_xml = None
        uploaded_file = request.files.get("saml_metadata_file")

        if uploaded_file and uploaded_file.filename:
            try:
                uploaded_metadata_xml = uploaded_file.read().decode("utf-8")
            except UnicodeDecodeError:
                flash("Uploaded metadata file must be valid UTF-8 XML.", "error")
                return redirect(url_for("launchpad_ui.settings_integrations_saml"))

        set_setting("auth.saml.enabled", 1 if request.form.get("saml_enabled") == "1" else 0)
        set_setting("auth.saml.idp_type", (request.form.get("saml_idp_type") or "generic").strip())
        set_setting("auth.saml.metadata_url", (request.form.get("saml_metadata_url") or "").strip())

        metadata_xml_value = uploaded_metadata_xml
        if metadata_xml_value is None:
            metadata_xml_value = (get_setting("auth.saml.metadata_xml", "") or "").strip()

        set_setting("auth.saml.metadata_xml", metadata_xml_value, is_sensitive=1)
        set_setting("auth.saml.idp_entity_id", (request.form.get("saml_idp_entity_id") or "").strip())
        set_setting("auth.saml.sso_url", (request.form.get("saml_sso_url") or "").strip())
        set_setting("auth.saml.slo_url", (request.form.get("saml_slo_url") or "").strip())
        set_setting("auth.saml.x509_cert", (request.form.get("saml_x509_cert") or "").strip(), is_sensitive=1)
        set_setting("auth.saml.sp_entity_id", (request.form.get("saml_sp_entity_id") or "").strip())
        set_setting("auth.saml.acs_url", (request.form.get("saml_acs_url") or "").strip())
        set_setting("auth.saml.logout_url", (request.form.get("saml_logout_url") or "").strip())
        set_setting("auth.saml.attr.email", (request.form.get("saml_attr_email") or "email").strip())
        set_setting("auth.saml.attr.first_name", (request.form.get("saml_attr_first_name") or "first_name").strip())
        set_setting("auth.saml.attr.last_name", (request.form.get("saml_attr_last_name") or "last_name").strip())
        set_setting("auth.saml.attr.display_name", (request.form.get("saml_attr_display_name") or "display_name").strip())
        set_setting("auth.saml.attr.groups", (request.form.get("saml_attr_groups") or "groups").strip())

        flash("SAML integration settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_integrations_saml"))

    return render_template(
        "launchpad_ui/settings/integrations_saml.html",
        active_section="integrations",
        settings=saml_integration_settings(),
    )


@launchpad_ui_bp.route("/settings/integrations/snipeit", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.snipeops.view")
def settings_integrations_snipeit():
    current_settings = get_snipeops_settings()

    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.snipeops.manage",
            "You do not have permission to update Snipe-IT integration settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_integrations_snipeit"))

        enabled = 1 if request.form.get("snipeit_enabled") == "1" else 0
        base_url = (request.form.get("base_url") or "").strip()
        verify_ssl = 1 if request.form.get("verify_ssl") == "1" else 0
        new_api_token = (request.form.get("api_token") or "").strip()

        set_setting("snipeops.enabled", enabled)
        set_setting("snipeops.base_url", base_url)
        set_setting("snipeops.verify_ssl", verify_ssl)

        if new_api_token:
            set_setting("snipeops.api_token", new_api_token, is_sensitive=1)

        flash("Snipe-IT integration settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_integrations_snipeit"))

    settings = {
        "snipeit_enabled": current_settings["enabled"],
        "base_url": current_settings["base_url"],
        "verify_ssl": current_settings["verify_ssl"],
        "has_api_token": current_settings["has_api_token"],
        "token_source": current_settings["token_source"],
        "is_configured": current_settings["is_configured"],
    }

    return render_template(
        "launchpad_ui/settings/integrations_snipeit.html",
        active_section="integrations",
        settings=settings,
    )

@launchpad_ui_bp.route("/settings/integrations/mosyle", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.snipeops.view")
def settings_integrations_mosyle():
    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.snipeops.manage",
            "You do not have permission to update Mosyle integration settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_integrations_mosyle"))

        enabled = 1 if request.form.get("mosyle_enabled") == "1" else 0
        base_url = (
            request.form.get("mosyle_base_url")
            or "https://managerapi.mosyle.com/v2"
        ).strip().rstrip("/")
        username = (request.form.get("mosyle_username") or "").strip()
        access_token = (request.form.get("mosyle_access_token") or "").strip()

        set_setting("integrations.mosyle.enabled", enabled)
        set_setting("integrations.mosyle.base_url", base_url)
        set_setting("integrations.mosyle.username", username)

        if access_token:
            set_setting("integrations.mosyle.access_token", access_token, is_sensitive=1)

        flash("Mosyle integration settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_integrations_mosyle"))

    return render_template(
        "launchpad_ui/settings/integrations_mosyle.html",
        active_section="integrations",
        settings=mosyle_integration_settings(),
    )

@launchpad_ui_bp.route("/settings/finance", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.finance.view")
def settings_finance():
    active_finance_tab = (
        (request.form.get("active_finance_tab") if request.method == "POST" else request.args.get("tab"))
        or "notifications"
    ).strip().lower()

    if active_finance_tab not in {"notifications", "template"}:
        active_finance_tab = "notifications"

    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.finance.manage",
            "You do not have permission to update Finance settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

        action = (request.form.get("action") or "save_settings").strip().lower()

        notifications_enabled = 1 if request.form.get("notifications_enabled") == "1" else 0
        use_record_recipients_first = 1 if request.form.get("use_record_recipients_first") == "1" else 0
        fallback_to_default_recipients = 1 if request.form.get("fallback_to_default_recipients") == "1" else 0

        include_title = 1 if request.form.get("include_title") == "1" else 0
        include_department_name = 1 if request.form.get("include_department_name") == "1" else 0
        include_vendor_name = 1 if request.form.get("include_vendor_name") == "1" else 0
        include_category_name = 1 if request.form.get("include_category_name") == "1" else 0
        include_renewal_date = 1 if request.form.get("include_renewal_date") == "1" else 0
        include_expiration_date = 1 if request.form.get("include_expiration_date") == "1" else 0
        include_cost = 1 if request.form.get("include_cost") == "1" else 0
        include_po_number = 1 if request.form.get("include_po_number") == "1" else 0
        include_account_code = 1 if request.form.get("include_account_code") == "1" else 0
        include_notes = 1 if request.form.get("include_notes") == "1" else 0
        include_record_link = 1 if request.form.get("include_record_link") == "1" else 0

        sender_email = (request.form.get("sender_email") or "").strip()
        default_recipients = (request.form.get("default_recipients") or "").strip()
        test_recipient_email = (request.form.get("test_recipient_email") or "").strip()
        default_days_before = (request.form.get("default_days_before") or "30").strip()
        subject_prefix = (request.form.get("subject_prefix") or "").strip()
        logo_width = (request.form.get("logo_width") or "180").strip()

        template_header = (request.form.get("template_header") or "").strip()
        template_intro = (request.form.get("template_intro") or "").strip()
        template_subject = (request.form.get("template_subject") or "").strip()
        template_footer = (request.form.get("template_footer") or "").strip()

        if notifications_enabled and not sender_email:
            flash("Sender email address is required when notifications are enabled.", "error")
            return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

        if notifications_enabled and not default_recipients and not use_record_recipients_first:
            flash("Enter default recipients or enable record-level recipients first.", "error")
            return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

        try:
            int(default_days_before)
        except ValueError:
            flash("Default days before renewal must be a whole number.", "error")
            return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

        try:
            int(logo_width)
        except ValueError:
            flash("Logo width must be a whole number.", "error")
            return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

        uploaded_logo = request.files.get("notification_logo")
        if uploaded_logo and uploaded_logo.filename:
            try:
                original_logo_name = uploaded_logo.filename
                logo_path = save_finance_notification_logo(uploaded_logo)
                set_setting("finance.notifications.logo_path", logo_path)
                set_setting("finance.notifications.logo_original_name", original_logo_name)
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

        set_setting("finance.notifications.enabled", notifications_enabled)
        set_setting("finance.notifications.sender_email", sender_email)
        set_setting("finance.notifications.default_recipients", default_recipients)
        set_setting("finance.notifications.test_recipient_email", test_recipient_email)
        set_setting("finance.notifications.use_record_recipients_first", use_record_recipients_first)
        set_setting("finance.notifications.fallback_to_default_recipients", fallback_to_default_recipients)
        set_setting("finance.notifications.default_days_before", default_days_before)
        set_setting("finance.notifications.subject_prefix", subject_prefix)
        set_setting("finance.notifications.logo_width", logo_width)

        set_setting("finance.notifications.template_header", template_header)
        set_setting("finance.notifications.template_intro", template_intro)
        set_setting("finance.notifications.template_subject", template_subject)
        set_setting("finance.notifications.template_footer", template_footer)

        set_setting("finance.notifications.include_title", include_title)
        set_setting("finance.notifications.include_department_name", include_department_name)
        set_setting("finance.notifications.include_vendor_name", include_vendor_name)
        set_setting("finance.notifications.include_category_name", include_category_name)
        set_setting("finance.notifications.include_renewal_date", include_renewal_date)
        set_setting("finance.notifications.include_expiration_date", include_expiration_date)
        set_setting("finance.notifications.include_cost", include_cost)
        set_setting("finance.notifications.include_po_number", include_po_number)
        set_setting("finance.notifications.include_account_code", include_account_code)
        set_setting("finance.notifications.include_notes", include_notes)
        set_setting("finance.notifications.include_record_link", include_record_link)

        if action == "send_test_email":
            if not sender_email:
                flash("Sender email is required to send a test email.", "error")
                return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

            if not test_recipient_email:
                flash("Test recipient email is required to send a test email.", "error")
                return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

            try:
                preview_context = build_finance_template_preview_context()
                preview_lines = build_finance_preview_lines(
                    {
                        "include_title": bool(include_title),
                        "include_department_name": bool(include_department_name),
                        "include_vendor_name": bool(include_vendor_name),
                        "include_category_name": bool(include_category_name),
                        "include_renewal_date": bool(include_renewal_date),
                        "include_expiration_date": bool(include_expiration_date),
                        "include_cost": bool(include_cost),
                        "include_po_number": bool(include_po_number),
                        "include_account_code": bool(include_account_code),
                        "include_notes": bool(include_notes),
                        "include_record_link": bool(include_record_link),
                    },
                    preview_context,
                )

                send_finance_test_email(
                    sender_email=sender_email,
                    recipient_email=test_recipient_email,
                    subject_template=template_subject,
                    subject_prefix=subject_prefix,
                    template_header=template_header,
                    template_intro=template_intro,
                    template_footer=template_footer,
                    preview_context=preview_context,
                    preview_lines=preview_lines,
                )

                flash(f"Test email sent to {test_recipient_email}.", "success")
            except Exception as exc:
                flash(f"Unable to send test email: {exc}", "error")

            return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

        flash("Finance notification settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_finance", tab=active_finance_tab))

    settings = finance_notification_settings()
    preview_context = build_finance_template_preview_context()

    preview_subject = render_finance_template_tokens(
        settings.get("template_subject", ""),
        preview_context,
    )

    preview_lines = build_finance_preview_lines(settings, preview_context)

    return render_template(
        "launchpad_ui/settings/finance.html",
        active_section="finance",
        active_finance_tab=active_finance_tab,
        settings=settings,
        preview_context=preview_context,
        preview_subject=preview_subject,
        preview_lines=preview_lines,
    )


@launchpad_ui_bp.route("/settings/integrations/email", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.view")
def settings_integrations_email():
    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.general.manage",
            "You do not have permission to update Email integration settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_integrations_email"))

        action = (request.form.get("action") or "save_settings").strip().lower()

        enabled = 1 if request.form.get("mail_enabled") == "1" else 0
        smtp_host = (request.form.get("smtp_host") or "").strip()
        smtp_port = (request.form.get("smtp_port") or "587").strip()
        smtp_username = (request.form.get("smtp_username") or "").strip()
        smtp_password = (request.form.get("smtp_password") or "").strip()
        smtp_use_tls = 1 if request.form.get("smtp_use_tls") == "1" else 0
        from_name = (request.form.get("from_name") or "").strip()
        test_email_recipient = (request.form.get("test_email_recipient") or "").strip()

        if enabled and not smtp_host:
            flash("SMTP host is required when email delivery is enabled.", "error")
            return redirect(url_for("launchpad_ui.settings_integrations_email"))

        try:
            int(smtp_port)
        except ValueError:
            flash("SMTP port must be a whole number.", "error")
            return redirect(url_for("launchpad_ui.settings_integrations_email"))

        set_setting("mail.enabled", enabled)
        set_setting("mail.smtp_host", smtp_host)
        set_setting("mail.smtp_port", smtp_port)
        set_setting("mail.smtp_username", smtp_username)

        if smtp_password:
            set_setting("mail.smtp_password", smtp_password, is_sensitive=1)

        set_setting("mail.smtp_use_tls", smtp_use_tls)
        set_setting("mail.from_name", from_name)
        set_setting("mail.test_recipient", test_email_recipient)

        if action == "send_test_email":
            if not test_email_recipient:
                flash("Enter a test recipient email.", "error")
                return redirect(url_for("launchpad_ui.settings_integrations_email"))

            if not smtp_username:
                flash("SMTP username is required to send a test email.", "error")
                return redirect(url_for("launchpad_ui.settings_integrations_email"))

            try:
                from modules.core.mail.service import send_mail

                send_mail(
                    sender_email=smtp_username,
                    recipient_email=test_email_recipient,
                    subject="Launchpad Email Test",
                    text_body="This is a test email from Launchpad SMTP integration.",
                    html_body="""
                        <html>
                          <body style="margin:0; padding:24px; background:#f8fafc; font-family:Arial, Helvetica, sans-serif; color:#0f172a;">
                            <div style="max-width:640px; margin:0 auto; background:#ffffff; border:1px solid #dbe4ee; border-radius:16px; overflow:hidden;">
                              <div style="padding:28px;">
                                <h1 style="margin:0 0 12px; font-size:24px; line-height:1.2; color:#0f172a;">
                                  Launchpad Email Test
                                </h1>
                                <p style="margin:0; font-size:15px; line-height:1.6; color:#475569;">
                                  Your Email / SMTP integration is working correctly.
                                </p>
                              </div>
                            </div>
                          </body>
                        </html>
                    """,
                )

                flash(f"Test email sent to {test_email_recipient}.", "success")
            except Exception as exc:
                flash(f"Test email failed: {exc}", "error")

            return redirect(url_for("launchpad_ui.settings_integrations_email"))

        flash("Email integration settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_integrations_email"))

    settings = {
        "mail_enabled": get_bool_setting("mail.enabled", False),
        "smtp_host": get_setting("mail.smtp_host", ""),
        "smtp_port": get_setting("mail.smtp_port", "587"),
        "smtp_username": get_setting("mail.smtp_username", ""),
        "smtp_use_tls": get_bool_setting("mail.smtp_use_tls", True),
        "from_name": get_setting("mail.from_name", ""),
        "test_email_recipient": get_setting("mail.test_recipient", ""),
        "has_password": bool((get_setting("mail.smtp_password", "") or "").strip()),
    }

    return render_template(
        "launchpad_ui/settings/integrations_email.html",
        active_section="integrations",
        settings=settings,
    )


@launchpad_ui_bp.route("/settings/integrations/api", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.snipeops.view")
def settings_integrations_api():
    generated_key = session.pop("generated_api_key", None)
    user_id = session.get("user_id")

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "create_api_key":
            if not _require_manage_permission(
                "launchpad.settings.snipeops.manage",
                "You do not have permission to manage integrations.",
            ):
                return redirect(url_for("launchpad_ui.settings_integrations_api"))

            friendly_name = (request.form.get("friendly_name") or "").strip()

            try:
                generated_key = create_api_key(
                    friendly_name=friendly_name,
                    created_by_user_id=user_id,
                )
                session["generated_api_key"] = generated_key
                flash("API key created. Copy it now; it will not be shown again.", "success")
            except ValueError as exc:
                flash(str(exc), "error")

            return redirect(url_for("launchpad_ui.settings_integrations_api"))

        if action == "revoke_api_key":
            if not _require_manage_permission(
                "launchpad.settings.snipeops.manage",
                "You do not have permission to manage integrations.",
            ):
                return redirect(url_for("launchpad_ui.settings_integrations_api"))

            api_key_id = request.form.get("api_key_id", type=int)
            if api_key_id:
                revoke_api_key(
                    api_key_id=api_key_id,
                    revoked_by_user_id=user_id,
                )
                flash("API key revoked.", "success")

            return redirect(url_for("launchpad_ui.settings_integrations_api"))

        if action == "delete_api_key":
            if not _require_manage_permission(
                "launchpad.settings.snipeops.manage",
                "You do not have permission to manage integrations.",
            ):
                return redirect(url_for("launchpad_ui.settings_integrations_api"))

            api_key_id = request.form.get("api_key_id", type=int)
            if api_key_id:
                delete_api_key(api_key_id=api_key_id)
                flash("API key deleted.", "success")

            return redirect(url_for("launchpad_ui.settings_integrations_api"))

    return render_template(
        "launchpad_ui/settings/integrations_api.html",
        active_section="integrations",
        api_keys=list_api_keys(),
        generated_key=generated_key,
    )


@launchpad_ui_bp.route("/account/theme", methods=["POST"])
@login_required
def update_account_theme():
    theme_preference = (request.form.get("theme_preference") or "").strip().lower()

    if theme_preference not in ("light", "dark"):
        return jsonify({"ok": False, "error": "Invalid theme."}), 400

    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "error": "User session is missing."}), 400

    update_user_theme_preference(user_id, theme_preference)
    session["theme_preference"] = theme_preference

    return jsonify({
        "ok": True,
        "theme_preference": theme_preference,
    })