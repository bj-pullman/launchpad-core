from __future__ import annotations

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

    base_url = db_url or env_url
    api_token = db_token or env_token

    verify_ssl = env_verify_ssl if db_verify_ssl is None else _to_bool(db_verify_ssl, True)

    return {
        "base_url": base_url.rstrip("/"),
        "api_token": api_token,
        "verify_ssl": verify_ssl,
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


def _request(method: str, endpoint: str, **kwargs):
    cfg = _get_snipeops_settings()

    if not cfg["base_url"]:
        raise ValueError("SnipeOps base URL is missing from settings.")

    if not cfg["verify_ssl"]:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    return requests.request(
        method=method,
        url=f"{cfg['base_url']}{endpoint}",
        headers=_headers(),
        verify=cfg["verify_ssl"],
        timeout=45,
        **kwargs,
    )


def _format_snipe_messages(payload):
    messages = payload.get("messages") or payload.get("message") or payload

    if isinstance(messages, dict):
        return "; ".join(f"{k}: {v}" for k, v in messages.items())

    if isinstance(messages, list):
        return "; ".join(str(x) for x in messages)

    return str(messages)


def checkout_asset_to_asset(
    *,
    child_asset_id: int,
    parent_asset_id: int,
    note: str = "Checked out by SnipeOps asset-to-asset helper.",
    delay_seconds: float = 0.35,
) -> dict:
    if delay_seconds > 0:
        time.sleep(float(delay_seconds))

    response = _request(
        "POST",
        f"/api/v1/hardware/{int(child_asset_id)}/checkout",
        json={
            "checkout_to_type": "asset",
            "assigned_asset": int(parent_asset_id),
            "note": note,
        },
    )

    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and data.get("status") == "error":
        raise ValueError(f"Snipe-IT checkout failed: {_format_snipe_messages(data)}")

    update_asset_status(
        asset_id=int(child_asset_id),
        status_name="Deployed",
    )

    return data

def checkin_asset(
    *,
    asset_id: int,
    note: str = "Checked in by SnipeOps checkout helper.",
    delay_seconds: float = 0.35,
) -> dict:
    if delay_seconds > 0:
        time.sleep(float(delay_seconds))

    response = _request(
        "POST",
        f"/api/v1/hardware/{int(asset_id)}/checkin",
        json={
            "note": note,
        },
    )

    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and data.get("status") == "error":
        raise ValueError(f"Snipe-IT checkin failed: {_format_snipe_messages(data)}")

    update_asset_status(
        asset_id=int(asset_id),
        status_name="Ready to Deploy",
    )

    return data

def build_asset_url(asset_id: int | str | None) -> str | None:
    cfg = _get_snipeops_settings()
    if not cfg["base_url"] or not asset_id:
        return None

    return f"{cfg['base_url']}/hardware/{int(asset_id)}"

def _json_response(response):
    response.raise_for_status()

    try:
        return response.json()
    except ValueError as exc:
        raise ValueError("Snipe-IT returned a non-JSON response.") from exc


def _ensure_snipe_write_success(payload, action):
    if isinstance(payload, dict) and payload.get("status") == "error":
        raise ValueError(f"Snipe-IT {action} failed: {_format_snipe_messages(payload)}")

    return payload


def update_asset_tag(*, asset_id: int, asset_tag: str) -> dict:
    clean_tag = str(asset_tag or "").strip()
    if not clean_tag:
        raise ValueError("Asset tag is required.")

    response = _request(
        "PATCH",
        f"/api/v1/hardware/{int(asset_id)}",
        json={"asset_tag": clean_tag},
    )

    return _ensure_snipe_write_success(
        _json_response(response),
        "asset tag update",
    )

def get_status_label_id_by_name(name: str) -> int | None:
    target = str(name or "").strip().lower()
    if not target:
        return None

    response = _request(
        "GET",
        "/api/v1/statuslabels",
        params={"search": target, "limit": 50},
    )
    response.raise_for_status()
    payload = response.json()

    for row in payload.get("rows", []):
        if str(row.get("name") or "").strip().lower() == target:
            return int(row["id"])

    return None


def update_asset_status(*, asset_id: int, status_name: str) -> dict:
    status_id = get_status_label_id_by_name(status_name)
    if not status_id:
        raise ValueError(f'Snipe-IT status label not found: "{status_name}"')

    response = _request(
        "PATCH",
        f"/api/v1/hardware/{int(asset_id)}",
        json={"status_id": status_id},
    )

    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and data.get("status") == "error":
        raise ValueError(f"Snipe-IT status update failed: {_format_snipe_messages(data)}")

    return data