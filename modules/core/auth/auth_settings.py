from modules.core.settings.settings_service import get_setting, get_bool_setting


def parse_list_setting(raw_value: str) -> list[str]:
    raw = (raw_value or "").strip()
    if not raw:
        return []

    normalized = raw.replace("\r", "\n").replace(",", "\n")
    return [item.strip().lower() for item in normalized.split("\n") if item.strip()]


def get_auth_runtime_settings() -> dict:
    return {
        # Sign-In Methods
        "primary_method": get_setting("auth.primary_method", "local"),

        "local_enabled": get_bool_setting("auth.local.enabled", True),
        "local_mode": get_setting("auth.local.mode", "breakglass_only"),
        "local_hide_form_when_restricted": get_bool_setting(
            "auth.local.hide_form_when_restricted", False
        ),

        "google_oidc_enabled": get_bool_setting("auth.google_oidc.enabled", False),
        "google_client_id": get_setting("auth.google_oidc.client_id", ""),
        "google_client_secret": get_setting("auth.google_oidc.client_secret", ""),
        "google_redirect_uri": get_setting("auth.google_oidc.redirect_uri", ""),
        "google_hosted_domain": get_setting("auth.google_oidc.hosted_domain", ""),

        "microsoft_oidc_enabled": get_bool_setting("auth.microsoft_oidc.enabled", False),
        "microsoft_tenant_id": get_setting("auth.microsoft_oidc.tenant_id", "common"),
        "microsoft_client_id": get_setting("auth.microsoft_oidc.client_id", ""),
        "microsoft_client_secret": get_setting("auth.microsoft_oidc.client_secret", ""),
        "microsoft_redirect_uri": get_setting("auth.microsoft_oidc.redirect_uri", ""),

        "saml_enabled": get_bool_setting("auth.saml.enabled", False),

        # Access Control
        "require_local_user_for_sso": get_bool_setting(
            "auth.access.require_local_user_for_sso", True
        ),
        "match_user_by": get_setting("auth.access.match_user_by", "email"),
        "deny_if_user_not_found": get_bool_setting(
            "auth.access.deny_if_user_not_found", True
        ),
        "deny_if_inactive": get_bool_setting("auth.access.deny_if_inactive", True),
        "allowed_domains": parse_list_setting(
            get_setting("auth.access.allowed_domains", "")
        ),
        "required_groups": parse_list_setting(
            get_setting("auth.access.required_groups", "")
        ),
        "required_groups_mode": get_setting(
            "auth.access.required_groups_mode", "any"
        ).strip().lower(),
        "allow_breakglass_with_sso": get_bool_setting(
            "auth.access.allow_breakglass_with_sso", True
        ),

        # Directory / group gate
        "google_directory_service_account_file": get_setting(
            "google.directory.service_account_file", ""
        ),
        "google_directory_delegated_admin": get_setting(
            "google.directory.delegated_admin", ""
        ),
    }