import os
import requests
import urllib3

from modules.core.settings.settings_service import get_setting
from apps.snipeops.import_by_scan.serial_utils import serial_candidates, normalize_serial


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
        "base_url": base_url.rstrip("/"),
        "api_token": api_token,
        "verify_ssl": verify_ssl,
    }


def _headers():
    cfg = _get_snipeops_settings()
    api_token = cfg["api_token"]

    if not api_token:
        raise ValueError("SnipeOps API token is missing from settings.")

    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(method, endpoint, **kwargs):
    cfg = _get_snipeops_settings()
    base_url = cfg["base_url"]
    verify_ssl = cfg["verify_ssl"]

    if not base_url:
        raise ValueError("SnipeOps base URL is missing from settings.")

    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    url = f"{base_url}{endpoint}"
    return requests.request(
        method=method,
        url=url,
        headers=_headers(),
        verify=verify_ssl,
        timeout=30,
        **kwargs,
    )


def find_asset_by_serial(raw_serial):
    candidates = serial_candidates(raw_serial)

    for cand in candidates:
        response = _request(
            "GET",
            "/api/v1/hardware",
            params={"search": cand},
        )
        response.raise_for_status()
        payload = response.json()

        for row in payload.get("rows", []):
            row_serial = normalize_serial(row.get("serial"))
            if row_serial in candidates:
                return row

    return None


def find_asset_by_asset_tag(asset_tag):
    response = _request(
        "GET",
        "/api/v1/hardware/bytag/" + str(asset_tag).strip(),
    )

    if response.status_code == 404:
        return None

    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict) and payload.get("status") == "error":
        return None

    return payload


def create_asset(profile, serial):
    payload = {
        "serial": str(serial).strip(),
        "model_id": int(profile["model_id"]),
        "status_id": int(profile["status_id"]),
        "rtd_location_id": int(profile["location_id"]),
    }

    if profile.get("asset_tag"):
        payload["asset_tag"] = str(profile["asset_tag"]).strip()

    if profile.get("supplier_id"):
        payload["supplier_id"] = int(profile["supplier_id"])

    if profile.get("depreciation_id"):
        payload["depreciation_id"] = int(profile["depreciation_id"])

    if profile.get("purchase_cost") is not None:
        payload["purchase_cost"] = profile["purchase_cost"]

    if profile.get("purchase_date"):
        payload["purchase_date"] = profile["purchase_date"]

    if profile.get("order_number"):
        payload["order_number"] = profile["order_number"]

    if profile.get("warranty_months") is not None:
        payload["warranty_months"] = int(profile["warranty_months"])

    response = _request(
        "POST",
        "/api/v1/hardware",
        json=payload,
    )
    response.raise_for_status()

    return {
        "data": response.json()
    }