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

from apps.staff_status.service import (
    get_department_record,
    list_active_departments_from_users,
    upsert_department_settings,
)

from apps.staff_status.access_service import (
    grant_department_access,
    revoke_department_access,
    list_staff_status_access_with_users,
)

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
    get_user_role_keys,
    remove_role_from_user,
)
from modules.core.identity.rbac_db import get_connection as get_rbac_connection
from modules.core.identity.user_service import get_user_by_id, update_user, create_user, list_users
from modules.core.settings.settings_service import get_setting, set_setting, get_bool_setting

from tasks.scheduler import configure_jobs


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

    db_enabled = get_bool_setting("snipeops.enabled", False)
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
    is_configured = bool(base_url and api_token)

    return {
        "enabled": db_enabled,
        "base_url": base_url,
        "api_token": api_token,
        "verify_ssl": verify_ssl,
        "has_api_token": bool(api_token),
        "token_source": token_source,
        "is_configured": is_configured,
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

def _authentication_settings():
    return {
        # Sign-In Methods
        "local_enabled": get_bool_setting("auth.local.enabled", True),
        "local_mode": get_setting("auth.local.mode", "breakglass_only"),
        "local_hide_form_when_restricted": get_bool_setting("auth.local.hide_form_when_restricted", False),

        "microsoft_oidc_enabled": get_bool_setting("auth.microsoft_oidc.enabled", False),
        "microsoft_client_id": get_setting("auth.microsoft_oidc.client_id", ""),
        "microsoft_client_secret": get_setting("auth.microsoft_oidc.client_secret", ""),
        "microsoft_tenant_id": get_setting("auth.microsoft_oidc.tenant_id", ""),
        "microsoft_redirect_uri": get_setting("auth.microsoft_oidc.redirect_uri", ""),

        "google_oidc_enabled": get_bool_setting("auth.google_oidc.enabled", False),
        "google_client_id": get_setting("auth.google_oidc.client_id", ""),
        "google_client_secret": get_setting("auth.google_oidc.client_secret", ""),
        "google_hosted_domain": get_setting("auth.google_oidc.hosted_domain", ""),
        "google_redirect_uri": get_setting("auth.google_oidc.redirect_uri", ""),

        "saml_enabled": get_bool_setting("auth.saml.enabled", False),
        "saml_idp_type": get_setting("auth.saml.idp_type", "generic"),
        "saml_metadata_url": get_setting("auth.saml.metadata_url", ""),
        "saml_metadata_xml": get_setting("auth.saml.metadata_xml", ""),
        "saml_idp_entity_id": get_setting("auth.saml.idp_entity_id", ""),
        "saml_sso_url": get_setting("auth.saml.sso_url", ""),
        "saml_slo_url": get_setting("auth.saml.slo_url", ""),
        "saml_x509_cert": get_setting("auth.saml.x509_cert", ""),
        "saml_sp_entity_id": get_setting("auth.saml.sp_entity_id", ""),
        "saml_acs_url": get_setting("auth.saml.acs_url", ""),
        "saml_logout_url": get_setting("auth.saml.logout_url", ""),
        "saml_attr_email": get_setting("auth.saml.attr.email", "email"),
        "saml_attr_first_name": get_setting("auth.saml.attr.first_name", "first_name"),
        "saml_attr_last_name": get_setting("auth.saml.attr.last_name", "last_name"),
        "saml_attr_display_name": get_setting("auth.saml.attr.display_name", "display_name"),
        "saml_attr_groups": get_setting("auth.saml.attr.groups", "groups"),

        "primary_method": get_setting("auth.primary_method", "local"),

        # Access Control
        "require_local_user_for_sso": get_bool_setting("auth.access.require_local_user_for_sso", True),
        "match_user_by": get_setting("auth.access.match_user_by", "email"),
        "deny_if_user_not_found": get_bool_setting("auth.access.deny_if_user_not_found", True),
        "deny_if_inactive": get_bool_setting("auth.access.deny_if_inactive", True),
        "allowed_domains": get_setting("auth.access.allowed_domains", ""),
        "required_groups": get_setting("auth.access.required_groups", ""),
        "required_groups_mode": get_setting("auth.access.required_groups_mode", "any"),
        "allow_breakglass_with_sso": get_bool_setting("auth.access.allow_breakglass_with_sso", True),
    }


def _provider_status(provider: str, settings: dict) -> str:
    if provider == "microsoft_oidc":
        required = [
            settings.get("microsoft_client_id"),
            settings.get("microsoft_client_secret"),
            settings.get("microsoft_tenant_id"),
        ]
        enabled = settings.get("microsoft_oidc_enabled")
    elif provider == "google_oidc":
        required = [
            settings.get("google_client_id"),
            settings.get("google_client_secret"),
        ]
        enabled = settings.get("google_oidc_enabled")
    elif provider == "saml":
        has_metadata = bool(settings.get("saml_metadata_url") or settings.get("saml_metadata_xml"))
        has_manual = bool(
            settings.get("saml_idp_entity_id")
            and settings.get("saml_sso_url")
            and settings.get("saml_x509_cert")
        )
        required = [has_metadata or has_manual]
        enabled = settings.get("saml_enabled")
    else:
        return "Disabled"

    if enabled:
        if all(required):
            return "Enabled"
        return "Incomplete"

    if all(required):
        return "Ready"

    if any(required):
        return "Incomplete"

    return "Disabled"


def _test_oidc_configuration(provider: str, form):
    if provider == "microsoft_oidc":
        tenant_id = (form.get("microsoft_tenant_id") or "").strip()
        client_id = (form.get("microsoft_client_id") or "").strip()
        client_secret = (form.get("microsoft_client_secret") or "").strip()

        if not client_secret:
            client_secret = (get_setting("auth.microsoft_oidc.client_secret", "") or "").strip()

        if not tenant_id:
            return {"ok": False, "message": "Microsoft Tenant ID is required."}
        if not client_id:
            return {"ok": False, "message": "Microsoft Client ID is required."}
        if not client_secret:
            return {"ok": False, "message": "Microsoft Client Secret is required."}

        discovery_url = f"https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"

    elif provider == "google_oidc":
        client_id = (form.get("google_client_id") or "").strip()
        client_secret = (form.get("google_client_secret") or "").strip()

        if not client_secret:
            client_secret = (get_setting("auth.google_oidc.client_secret", "") or "").strip()

        if not client_id:
            return {"ok": False, "message": "Google Client ID is required."}
        if not client_secret:
            return {"ok": False, "message": "Google Client Secret is required."}

        discovery_url = "https://accounts.google.com/.well-known/openid-configuration"
    else:
        return {"ok": False, "message": "Unsupported OIDC provider."}

    try:
        response = requests.get(discovery_url, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.RequestException as exc:
        return {
            "ok": False,
            "message": f"Could not reach the OIDC discovery endpoint: {exc}",
        }
    except ValueError:
        return {"ok": False, "message": "OIDC discovery endpoint returned invalid JSON."}

    required_keys = ["authorization_endpoint", "token_endpoint", "jwks_uri"]
    missing = [key for key in required_keys if not payload.get(key)]
    if missing:
        return {
            "ok": False,
            "message": f"OIDC discovery document is missing: {', '.join(missing)}.",
        }

    return {"ok": True, "message": "OIDC configuration looks valid."}


def _test_saml_configuration(form):
    metadata_url = (form.get("saml_metadata_url") or "").strip()
    metadata_xml = (form.get("saml_metadata_xml") or "").strip()
    entity_id = (form.get("saml_idp_entity_id") or "").strip()
    sso_url = (form.get("saml_sso_url") or "").strip()
    cert = (form.get("saml_x509_cert") or "").strip()
    sp_entity_id = (form.get("saml_sp_entity_id") or "").strip()
    acs_url = (form.get("saml_acs_url") or "").strip()

    if not cert:
        cert = (get_setting("auth.saml.x509_cert", "") or "").strip()

    if not metadata_xml:
        metadata_xml = (get_setting("auth.saml.metadata_xml", "") or "").strip()

    if not sp_entity_id:
        return {"ok": False, "message": "SP Entity ID is required."}
    if not acs_url:
        return {"ok": False, "message": "ACS URL is required."}

    if metadata_url:
        try:
            response = requests.get(metadata_url, timeout=10)
            response.raise_for_status()
            content = response.text
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "message": f"Could not fetch metadata URL: {exc}"}

        lowered = content.lower()
        if "entitydescriptor" not in lowered or "idpssodescriptor" not in lowered:
            return {"ok": False, "message": "Metadata XML does not appear to be valid IdP metadata."}
        if "singlesignonservice" not in lowered:
            return {"ok": False, "message": "Metadata XML is missing a SingleSignOnService entry."}
        return {"ok": True, "message": "SAML metadata URL looks valid."}

    if metadata_xml:
        lowered = metadata_xml.lower()
        if "entitydescriptor" not in lowered or "idpssodescriptor" not in lowered:
            return {"ok": False, "message": "Pasted metadata XML does not appear to be valid IdP metadata."}
        if "singlesignonservice" not in lowered:
            return {"ok": False, "message": "Pasted metadata XML is missing a SingleSignOnService entry."}
        return {"ok": True, "message": "SAML metadata XML looks valid."}

    if not entity_id:
        return {"ok": False, "message": "IdP Entity ID is required when not using metadata."}
    if not sso_url:
        return {"ok": False, "message": "SSO URL is required when not using metadata."}
    if not cert:
        return {"ok": False, "message": "X.509 certificate is required when not using metadata."}

    return {"ok": True, "message": "Manual SAML configuration looks valid."}

def _authentication_policy_settings():
    settings = _authentication_settings()
    return {
        "local_enabled": settings["local_enabled"],
        "local_mode": settings["local_mode"],
        "local_hide_form_when_restricted": settings["local_hide_form_when_restricted"],
        "primary_method": settings["primary_method"],
        "require_local_user_for_sso": settings["require_local_user_for_sso"],
        "match_user_by": settings["match_user_by"],
        "deny_if_user_not_found": settings["deny_if_user_not_found"],
        "deny_if_inactive": settings["deny_if_inactive"],
        "allowed_domains": settings["allowed_domains"],
        "required_groups": settings["required_groups"],
        "required_groups_mode": settings["required_groups_mode"],
        "allow_breakglass_with_sso": settings["allow_breakglass_with_sso"],
    }


def _microsoft_integration_settings():
    settings = _authentication_settings()
    return {
        "microsoft_oidc_enabled": settings["microsoft_oidc_enabled"],
        "microsoft_client_id": settings["microsoft_client_id"],
        "microsoft_tenant_id": settings["microsoft_tenant_id"],
        "microsoft_redirect_uri": settings["microsoft_redirect_uri"],
    }


def _google_integration_settings():
    settings = _authentication_settings()
    return {
        "google_oidc_enabled": settings["google_oidc_enabled"],
        "google_client_id": settings["google_client_id"],
        "google_hosted_domain": settings["google_hosted_domain"],
        "google_redirect_uri": settings["google_redirect_uri"],
    }


def _saml_integration_settings():
    settings = _authentication_settings()
    return {
        "saml_enabled": settings["saml_enabled"],
        "saml_idp_type": settings["saml_idp_type"],
        "saml_metadata_url": settings["saml_metadata_url"],
        "saml_metadata_xml": settings["saml_metadata_xml"],
        "saml_idp_entity_id": settings["saml_idp_entity_id"],
        "saml_sso_url": settings["saml_sso_url"],
        "saml_slo_url": settings["saml_slo_url"],
        "saml_x509_cert": settings["saml_x509_cert"],
        "saml_sp_entity_id": settings["saml_sp_entity_id"],
        "saml_acs_url": settings["saml_acs_url"],
        "saml_logout_url": settings["saml_logout_url"],
        "saml_attr_email": settings["saml_attr_email"],
        "saml_attr_first_name": settings["saml_attr_first_name"],
        "saml_attr_last_name": settings["saml_attr_last_name"],
        "saml_attr_display_name": settings["saml_attr_display_name"],
        "saml_attr_groups": settings["saml_attr_groups"],
    }

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


@launchpad_ui_bp.route("/settings/snipeops")
@login_required
@require_permission("launchpad.settings.snipeops.view")
def settings_snipeops():
    return redirect(url_for("launchpad_ui.settings_integrations_snipeit"))


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

    settings = _authentication_policy_settings()

    return render_template(
        "launchpad_ui/settings/authentication.html",
        active_section="authentication",
        settings=settings,
    )


@launchpad_ui_bp.route("/settings/authentication/test-connection", methods=["POST"])
@login_required
@require_permission("launchpad.settings.saml.view")
def settings_authentication_test_connection():
    if "launchpad.settings.saml.manage" not in _user_permissions():
        return jsonify({
            "ok": False,
            "message": "You do not have permission to test authentication settings.",
        }), 403

    provider = (request.form.get("provider") or "").strip().lower()

    if provider == "microsoft_oidc":
        result = _test_oidc_configuration("microsoft_oidc", request.form)
    elif provider == "google_oidc":
        result = _test_oidc_configuration("google_oidc", request.form)
    elif provider == "saml":
        result = _test_saml_configuration(request.form)
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
        inherited_permissions = access_summary.get("inherited_permissions", []),
        direct_permissions = access_summary.get("direct_permissions", []),
        effective_permissions = access_summary.get("effective_permissions", []),
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
        board_refresh_seconds = (
            request.form.get("board_refresh_seconds") or "15"
        ).strip()

        set_setting("staff_status.enabled_departments", ",".join(enabled_departments))
        set_setting("staff_status.daily_reset_enabled", daily_reset_enabled)
        set_setting("staff_status.daily_reset_time", daily_reset_time)
        set_setting("staff_status.board_refresh_seconds", board_refresh_seconds)

        for department_name in available_departments:
            is_enabled = department_name in enabled_departments
            home_location = (
                request.form.get(f"home_location_{department_name}") or ""
            ).strip()

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

        department_rows.append(
            {
                "department_name": department_name,
                "is_enabled": department_name in enabled_departments,
                "home_location": home_location or "",
                "kiosk_enabled": kiosk_enabled,
                "kiosk_token": kiosk_token,
                "board_token": board_token,
            }
        )

    settings = {
        "enabled_departments": enabled_departments,
        "daily_reset_enabled": get_bool_setting("staff_status.daily_reset_enabled", True),
        "daily_reset_time": get_setting("staff_status.daily_reset_time", "01:00"),
        "board_refresh_seconds": get_setting(
            "staff_status.board_refresh_seconds", "15"
        ),
    }

    department_operator_assignments = list_staff_status_access_with_users()
    assignable_users = list_users(active_only=True)

    return render_template(
        "launchpad_ui/settings/staff_status.html",
        active_section="staff_status",
        settings=settings,
        department_rows=department_rows,
        department_operator_assignments=department_operator_assignments,
        assignable_users=assignable_users,
    )

@launchpad_ui_bp.route("/settings/integrations")
@login_required
@require_permission("launchpad.settings.view")
def settings_integrations():
    user_permissions = _user_permissions()

    return render_template(
        "launchpad_ui/settings/integrations.html",
        active_section="integrations",
        can_view_microsoft="launchpad.settings.saml.view" in user_permissions,
        can_view_google="launchpad.settings.saml.view" in user_permissions,
        can_view_saml="launchpad.settings.saml.view" in user_permissions,
        can_view_snipeit="launchpad.settings.snipeops.view" in user_permissions,
    )


@launchpad_ui_bp.route("/settings/integrations/microsoft", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.saml.view")
def settings_integrations_microsoft():
    if request.method == "POST":
        if not _require_manage_permission(
            "launchpad.settings.saml.manage",
            "You do not have permission to update Microsoft integration settings.",
        ):
            return redirect(url_for("launchpad_ui.settings_integrations_microsoft"))

        set_setting("auth.microsoft_oidc.enabled", 1 if request.form.get("microsoft_oidc_enabled") == "1" else 0)
        set_setting("auth.microsoft_oidc.client_id", (request.form.get("microsoft_client_id") or "").strip())
        microsoft_secret = (request.form.get("microsoft_client_secret") or "").strip()
        if microsoft_secret:
            set_setting("auth.microsoft_oidc.client_secret", microsoft_secret, is_sensitive=1)
        set_setting("auth.microsoft_oidc.tenant_id", (request.form.get("microsoft_tenant_id") or "common").strip())
        set_setting("auth.microsoft_oidc.redirect_uri", (request.form.get("microsoft_redirect_uri") or "").strip())

        flash("Microsoft integration settings saved.", "success")
        return redirect(url_for("launchpad_ui.settings_integrations_microsoft"))

    settings = _microsoft_integration_settings()
    return render_template(
        "launchpad_ui/settings/integrations_microsoft.html",
        active_section="integrations",
        settings=settings,
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

    settings = _google_integration_settings()
    return render_template(
        "launchpad_ui/settings/integrations_google.html",
        active_section="integrations",
        settings=settings,
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

    settings = _saml_integration_settings()
    return render_template(
        "launchpad_ui/settings/integrations_saml.html",
        active_section="integrations",
        settings=settings,
    )

@launchpad_ui_bp.route("/settings/integrations/snipeit", methods=["GET", "POST"])
@login_required
@require_permission("launchpad.settings.snipeops.view")
def settings_integrations_snipeit():
    current_settings = _get_snipeops_settings()

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