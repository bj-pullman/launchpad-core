import os
from pathlib import Path
import secrets

import requests
from flask import session
from werkzeug.routing import BuildError

from apps.launchpad_ui.permissions import (
    get_visible_settings_sections,
    get_visible_launchpad_apps,
)
from modules.core.identity.rbac_db import get_connection as get_rbac_connection
from modules.core.identity.rbac_service import build_permission_catalog
from modules.core.settings.settings_service import get_setting, get_bool_setting


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


def user_permissions():
    return set(session.get("user_permissions", []))


def truncate_text(value: str, max_length: int = 44) -> str:
    value = (value or "").strip()
    if len(value) <= max_length:
        return value

    truncated = value[: max_length - 3].rstrip(", ").rstrip()
    return f"{truncated}..."


def group_permission_catalog():
    catalog = build_permission_catalog()
    grouped = {}

    for item in catalog:
        section = item["section"]
        group = item["group"]

        grouped.setdefault(section, {})
        grouped[section].setdefault(group, [])
        grouped[section][group].append(item)

    return grouped


def to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def get_snipeops_settings():
    env_url = os.getenv("SNIPE_URL", "").strip()
    env_token = os.getenv("SNIPE_API_TOKEN", "").strip()
    env_verify_ssl = to_bool(os.getenv("VERIFY_SSL", "true"), True)

    db_enabled = get_bool_setting("snipeops.enabled", False)
    db_url = (get_setting("snipeops.base_url", "") or "").strip()
    db_token = (get_setting("snipeops.api_token", "") or "").strip()
    db_verify_ssl = get_setting("snipeops.verify_ssl", None)

    base_url = db_url or env_url
    api_token = db_token or env_token

    if db_verify_ssl is None:
        verify_ssl = env_verify_ssl
    else:
        verify_ssl = to_bool(db_verify_ssl, True)

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


def test_snipeit_connection(base_url: str, api_token: str, verify_ssl: bool):
    if not base_url:
        return {"ok": False, "message": "Snipe-IT Base URL is required."}

    if not api_token:
        return {"ok": False, "message": "A Snipe-IT API key is required."}

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
        return {"ok": False, "message": "SSL verification failed while connecting to Snipe-IT."}
    except requests.exceptions.ConnectTimeout:
        return {"ok": False, "message": "Connection to Snipe-IT timed out."}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "message": "Could not reach the Snipe-IT server."}
    except requests.exceptions.RequestException as exc:
        return {"ok": False, "message": f"Connection test failed: {exc}"}

    if response.status_code in (401, 403):
        return {"ok": False, "message": "Authentication failed. Check the API key."}

    if not response.ok:
        return {"ok": False, "message": f"Snipe-IT returned HTTP {response.status_code}."}

    try:
        payload = response.json()
    except ValueError:
        return {"ok": False, "message": "Snipe-IT returned a non-JSON response."}

    total = payload.get("total")
    if total is not None:
        return {
            "ok": True,
            "message": f"Connection successful. Retrieved status labels successfully (total: {total}).",
        }

    return {"ok": True, "message": "Connection successful."}


def authentication_settings():
    return {
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

        "require_local_user_for_sso": get_bool_setting("auth.access.require_local_user_for_sso", True),
        "match_user_by": get_setting("auth.access.match_user_by", "email"),
        "deny_if_user_not_found": get_bool_setting("auth.access.deny_if_user_not_found", True),
        "deny_if_inactive": get_bool_setting("auth.access.deny_if_inactive", True),
        "allowed_domains": get_setting("auth.access.allowed_domains", ""),
        "required_groups": get_setting("auth.access.required_groups", ""),
        "required_groups_mode": get_setting("auth.access.required_groups_mode", "any"),
        "allow_breakglass_with_sso": get_bool_setting("auth.access.allow_breakglass_with_sso", True),
    }


def provider_status(provider: str, settings: dict) -> str:
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


def public_base_url() -> str:
    return (get_setting("general.public_base_url", "") or "").strip().rstrip("/")


def build_public_url(path: str) -> str:
    base_url = public_base_url()
    clean_path = "/" + (path or "").lstrip("/")

    if not base_url:
        return clean_path

    return f"{base_url}{clean_path}"


def test_oidc_configuration(provider: str, form):
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
        return {"ok": False, "message": f"Could not reach the OIDC discovery endpoint: {exc}"}
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


def test_saml_configuration(form):
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


def authentication_policy_settings():
    settings = authentication_settings()
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


def microsoft_integration_settings():
    settings = authentication_settings()

    return {
        # Microsoft OIDC / Sign-in
        "microsoft_oidc_enabled": settings["microsoft_oidc_enabled"],
        "microsoft_client_id": settings["microsoft_client_id"],
        "microsoft_tenant_id": settings["microsoft_tenant_id"],
        "microsoft_redirect_uri": settings["microsoft_redirect_uri"],
        
        # Microsoft Intune / Graph
        "intune_enabled": get_bool_setting("integrations.microsoft.intune.enabled", False),
        "intune_tenant_id": get_setting("integrations.microsoft.intune.tenant_id", ""),
        "intune_client_id": get_setting("integrations.microsoft.intune.client_id", ""),
        "intune_graph_base_url": get_setting(
            "integrations.microsoft.intune.graph_base_url",
            "https://graph.microsoft.com/v1.0",
        ),
        "intune_has_client_secret": bool(
            (get_setting("integrations.microsoft.intune.client_secret", "") or "").strip()
        ),
        "entra_user_sync_enabled": get_bool_setting("entra.user_sync.enabled", False),
        "entra_user_sync_schedule_enabled": get_bool_setting("entra.user_sync.schedule_enabled", False),
        "entra_user_sync_tenant_id": get_setting("entra.tenant_id", ""),
        "entra_user_sync_client_id": get_setting("entra.client_id", ""),
        "entra_user_sync_has_client_secret": bool((get_setting("entra.client_secret", "") or "").strip()),
        "entra_user_sync_schedule_hours": get_setting("entra.user_sync.schedule_hours", "6,14"),
        "entra_user_sync_group_id": get_setting("entra.user_sync.group_id", ""),
    }


def google_integration_settings():
    settings = authentication_settings()
    return {
        "google_oidc_enabled": settings["google_oidc_enabled"],
        "google_client_id": settings["google_client_id"],
        "google_hosted_domain": settings["google_hosted_domain"],
        "google_redirect_uri": settings["google_redirect_uri"],
    }


def saml_integration_settings():
    settings = authentication_settings()
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


def finance_notification_logo_dir() -> Path:
    base_dir = Path(__file__).resolve().parents[2]
    logo_dir = base_dir / "static" / "finance" / "branding"
    logo_dir.mkdir(parents=True, exist_ok=True)
    return logo_dir


def save_finance_notification_logo(upload) -> str:
    if not upload or not upload.filename:
        raise ValueError("No logo file selected.")

    suffix = Path(upload.filename).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
    if suffix not in allowed:
        raise ValueError("Unsupported logo type. Allowed: PNG, JPG, JPEG, WEBP, SVG.")

    file_bytes = upload.read()
    if not file_bytes:
        raise ValueError("The selected logo file was empty.")

    stored_name = f"finance_notification_logo_{secrets.token_hex(8)}{suffix}"
    stored_path = finance_notification_logo_dir() / stored_name

    with open(stored_path, "wb") as f:
        f.write(file_bytes)

    return f"finance/branding/{stored_name}"


def format_money_preview(value: str) -> str:
    raw = (value or "").strip()
    return raw or "$4,500.00"


def build_finance_template_preview_context():
    record_url = build_public_url("/finance/records/123")

    return {
        "title": "Adobe Creative Cloud",
        "department_name": "Technology",
        "vendor_name": "Adobe",
        "category_name": "Software",
        "renewal_date": "07/01/2026",
        "expiration_date": "06/30/2026",
        "cost": "$4,500.00",
        "po_number": "PO-240156",
        "account_code": "10-2660-640",
        "notification_recipients": "tech@sheridanschools.org",
        "notes": "Annual district renewal for staff licensing.",
        "record_url": record_url,
        "days_until_renewal": "45",
    }


def render_finance_template_tokens(template: str, context: dict) -> str:
    rendered = template or ""
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", str(value or "—"))
    return rendered


def finance_notification_settings():
    return {
        "notifications_enabled": get_bool_setting("finance.notifications.enabled", False),
        "sender_email": get_setting("finance.notifications.sender_email", ""),
        "default_recipients": get_setting("finance.notifications.default_recipients", ""),
        "test_recipient_email": get_setting("finance.notifications.test_recipient_email", ""),
        "use_record_recipients_first": get_bool_setting("finance.notifications.use_record_recipients_first", True),
        "fallback_to_default_recipients": get_bool_setting("finance.notifications.fallback_to_default_recipients", True),
        "default_days_before": get_setting("finance.notifications.default_days_before", "30"),
        "subject_prefix": get_setting("finance.notifications.subject_prefix", "Renewal Reminder"),
        "logo_path": get_setting("finance.notifications.logo_path", ""),
        "logo_width": get_setting("finance.notifications.logo_width", "180"),
        "template_header": get_setting("finance.notifications.template_header", "Renewal Reminder"),
        "template_intro": get_setting(
            "finance.notifications.template_intro",
            "The following finance record is approaching renewal.",
        ),
        "template_subject": get_setting(
            "finance.notifications.template_subject",
            "{{ title }} renews on {{ renewal_date }}",
        ),
        "template_footer": get_setting(
            "finance.notifications.template_footer",
            "This message was generated by Launchpad Finance notifications.",
        ),
        "include_title": get_bool_setting("finance.notifications.include_title", True),
        "include_department_name": get_bool_setting("finance.notifications.include_department_name", True),
        "include_vendor_name": get_bool_setting("finance.notifications.include_vendor_name", True),
        "include_category_name": get_bool_setting("finance.notifications.include_category_name", True),
        "include_renewal_date": get_bool_setting("finance.notifications.include_renewal_date", True),
        "include_expiration_date": get_bool_setting("finance.notifications.include_expiration_date", True),
        "include_cost": get_bool_setting("finance.notifications.include_cost", True),
        "include_po_number": get_bool_setting("finance.notifications.include_po_number", False),
        "include_account_code": get_bool_setting("finance.notifications.include_account_code", False),
        "include_notes": get_bool_setting("finance.notifications.include_notes", True),
        "include_record_link": get_bool_setting("finance.notifications.include_record_link", True),
        "logo_original_name": get_setting("finance.notifications.logo_original_name", ""),
    }


def build_finance_preview_lines(settings: dict, preview_context: dict) -> list[dict]:
    lines = []

    field_map = [
        ("include_title", "Title", "title"),
        ("include_department_name", "Department", "department_name"),
        ("include_vendor_name", "Vendor", "vendor_name"),
        ("include_category_name", "Category", "category_name"),
        ("include_renewal_date", "Renewal Date", "renewal_date"),
        ("include_expiration_date", "Expiration Date", "expiration_date"),
        ("include_cost", "Cost", "cost"),
        ("include_po_number", "PO Number", "po_number"),
        ("include_account_code", "Account Code", "account_code"),
        ("include_notes", "Notes", "notes"),
        ("include_record_link", "Record Link", "record_url"),
    ]

    for setting_key, label, context_key in field_map:
        if settings.get(setting_key):
            lines.append(
                {
                    "label": label,
                    "value": preview_context.get(context_key, "—"),
                    "is_link": context_key == "record_url",
                }
            )

    return lines

def mosyle_integration_settings():
    return {
        "mosyle_enabled": get_bool_setting("integrations.mosyle.enabled", False),
        "mosyle_base_url": get_setting("integrations.mosyle.base_url", "https://managerapi.mosyle.com/v2"),
        "mosyle_username": get_setting("integrations.mosyle.username", ""),
        "mosyle_access_token": bool((get_setting("integrations.mosyle.access_token", "") or "").strip()),
        "mosyle_has_password": bool((get_setting("integrations.mosyle.password", "") or "").strip()),
    }