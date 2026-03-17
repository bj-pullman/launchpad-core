import os
import requests

from modules.core.settings.settings_service import get_setting


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

    return {
        "base_url": base_url,
        "api_token": api_token,
        "verify_ssl": verify_ssl,
    }


def _headers():
    settings = _get_snipeops_settings()
    api_token = settings["api_token"]

    if not api_token:
        raise ValueError("SnipeOps API token is missing from settings.")

    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_paginated(endpoint, limit=500):
    settings = _get_snipeops_settings()
    base_url = settings["base_url"]
    verify_ssl = settings["verify_ssl"]

    if not base_url:
        raise ValueError("SnipeOps base URL is missing from settings.")

    out = []
    offset = 0

    while True:
        url = f"{base_url.rstrip('/')}{endpoint}?limit={limit}&offset={offset}"
        response = requests.get(
            url,
            headers=_headers(),
            verify=verify_ssl,
            timeout=30,
        )
        response.raise_for_status()

        payload = response.json()
        rows = payload.get("rows") or []
        out.extend(rows)

        total = payload.get("total")
        if total is not None and len(out) >= int(total):
            break
        if not rows:
            break

        offset += limit

    return out


def fetch_models():
    return get_paginated("/api/v1/models")


def fetch_locations():
    return get_paginated("/api/v1/locations")


def fetch_statuslabels():
    return get_paginated("/api/v1/statuslabels")


def fetch_suppliers():
    return get_paginated("/api/v1/suppliers")


def fetch_depreciations():
    return get_paginated("/api/v1/depreciations")