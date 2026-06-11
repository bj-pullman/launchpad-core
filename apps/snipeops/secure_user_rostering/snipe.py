import os
import time
import requests
import urllib3

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

    return {
        "base_url": (db_url or env_url).rstrip("/"),
        "api_token": db_token or env_token,
        "verify_ssl": env_verify_ssl if db_verify_ssl is None else _to_bool(db_verify_ssl, True),
    }


def _headers():
    cfg = _get_snipeops_settings()

    if not cfg["api_token"]:
        raise ValueError("SnipeOps API token is missing from settings.")

    return {
        "Authorization": f"Bearer {cfg['api_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(method, endpoint, **kwargs):
    cfg = _get_snipeops_settings()

    if not cfg["base_url"]:
        raise ValueError("SnipeOps base URL is missing from settings.")

    if not cfg["verify_ssl"]:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    response = requests.request(
        method=method,
        url=f"{cfg['base_url']}{endpoint}",
        headers=_headers(),
        verify=cfg["verify_ssl"],
        timeout=45,
        **kwargs,
    )

    response.raise_for_status()

    try:
        payload = response.json()
    except Exception:
        payload = {"raw_response": response.text}

    if isinstance(payload, dict) and payload.get("status") == "error":
        raise ValueError(f"Snipe-IT API error: {payload}")

    return payload


def get_paginated(endpoint, limit=250):
    out = []
    offset = 0

    while True:
        payload = _request(
            "GET",
            endpoint,
            params={
                "limit": limit,
                "offset": offset,
            },
        )

        rows = payload.get("rows") or []
        total = payload.get("total")

        out.extend(rows)

        if total is not None and len(out) >= int(total):
            break

        if not rows:
            break

        offset += limit
        time.sleep(0.15)

    return out


def fetch_users(limit=250):
    return get_paginated("/api/v1/users", limit=limit)


def fetch_user_assets(user_id):
    return get_paginated(f"/api/v1/users/{int(user_id)}/assets", limit=250)


def fetch_user(user_id):
    return _request("GET", f"/api/v1/users/{int(user_id)}")


def delete_user(user_id):
    return _request("DELETE", f"/api/v1/users/{int(user_id)}")


def checkin_asset(asset_id, note=None):
    payload = {}

    if note:
        payload["note"] = note

    return _request(
        "POST",
        f"/api/v1/hardware/{int(asset_id)}/checkin",
        json=payload,
    )


def checkout_asset_to_user(asset_id, user_id, note=None):
    payload = {
        "checkout_to_type": "user",
        "assigned_user": int(user_id),
    }

    if note:
        payload["note"] = note

    return _request(
        "POST",
        f"/api/v1/hardware/{int(asset_id)}/checkout",
        json=payload,
    )