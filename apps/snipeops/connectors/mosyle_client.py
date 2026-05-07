import requests

from modules.core.settings.settings_service import get_setting, get_bool_setting
from apps.snipeops.import_by_scan.serial_utils import normalize_serial


def _settings():
    return {
        "enabled": get_bool_setting("integrations.mosyle.enabled", False),
        "base_url": (
            get_setting("integrations.mosyle.base_url", "https://managerapi.mosyle.com/v2")
            or "https://managerapi.mosyle.com/v2"
        ).strip().rstrip("/"),
        "access_token": (get_setting("integrations.mosyle.access_token", "") or "").strip(),
        "username": (get_setting("integrations.mosyle.username", "") or "").strip(),
        "password": (get_setting("integrations.mosyle.password", "") or "").strip(),
    }


def _login(cfg):
    response = requests.post(
        f"{cfg['base_url']}/login",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "accessToken": cfg["access_token"],
            "email": cfg["username"],
            "password": cfg["password"],
        },
        timeout=30,
    )

    if not response.ok:
        raise ValueError(
            f"Mosyle login failed: HTTP {response.status_code} - {response.text}"
        )

    bearer = response.headers.get("Authorization", "").strip()
    if not bearer:
        raise ValueError("Mosyle login succeeded but no Authorization header was returned.")

    return bearer


def _extract_rows(payload):
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    response = payload.get("response")
    if isinstance(response, list):
        return response

    if isinstance(response, dict):
        return (
            response.get("devices")
            or response.get("rows")
            or response.get("data")
            or response.get("results")
            or []
        )

    data = payload.get("data")
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        return (
            data.get("devices")
            or data.get("rows")
            or data.get("results")
            or []
        )

    return (
        payload.get("devices")
        or payload.get("rows")
        or payload.get("results")
        or []
    )


def _first_value(row, keys):
    for key in keys:
        value = row.get(key)
        if value:
            return value
    return ""


def _first_email(row):
    keys = [
        "email",
        "user_email",
        "userEmail",
        "username",
        "user_name",
        "userName",
        "managed_user_email",
        "managedUserEmail",
        "assigned_user_email",
        "assignedUserEmail",
    ]

    for key in keys:
        value = str(row.get(key) or "").strip()
        if "@" in value:
            return value

    user = row.get("user") or row.get("assigned_user") or row.get("assignedUser")
    if isinstance(user, dict):
        for key in ("email", "username", "userName", "name"):
            value = str(user.get(key) or "").strip()
            if "@" in value:
                return value

    return ""


def _normalize_device(row):
    serial = normalize_serial(
        _first_value(row, [
            "serial_number",
            "serialNumber",
            "serial",
            "SerialNumber",
        ])
    )

    if not serial:
        return None

    model = _first_value(row, [
        "model_name",
        "modelName",
        "device_model",
        "deviceModel",
        "product_name",
        "productName",
        "marketing_name",
        "marketingName",
        "model_identifier",
        "modelIdentifier",
        "model",
        "Model",
    ])

    os_version = _first_value(row, [
        "os_version",
        "osVersion",
        "OSVersion",
        "system_version",
        "systemVersion",
        "version",
        "Version",
    ])

    assigned_user = (
        _first_email(row)
        or _first_value(row, [
            "username",
            "user_name",
            "userName",
            "user",
            "email",
            "assigned_user",
            "assignedUser",
        ])
    )

    return {
        "source": "mosyle",
        "source_id": row.get("id") or row.get("device_id") or row.get("DeviceID") or "",
        "name": _first_value(row, [
            "device_name",
            "deviceName",
            "name",
            "DeviceName",
        ]),
        "serial": serial,
        "raw_serial": _first_value(row, [
            "serial_number",
            "serialNumber",
            "serial",
            "SerialNumber",
        ]),
        "manufacturer": "Apple",
        "model": model,
        "os": _first_value(row, [
            "os",
            "os_type",
            "osType",
            "OS",
        ]),
        "os_version": os_version,
        "assigned_user": assigned_user,
        "last_seen": _first_value(row, [
            "last_checkin",
            "lastCheckin",
            "last_seen",
            "lastSeen",
        ]),
        "raw_model_data": str({
            "model": row.get("model"),
            "model_name": row.get("model_name"),
            "modelName": row.get("modelName"),
            "device_model": row.get("device_model"),
            "deviceModel": row.get("deviceModel"),
            "product_name": row.get("product_name"),
            "productName": row.get("productName"),
            "model_identifier": row.get("model_identifier"),
            "modelIdentifier": row.get("modelIdentifier"),
            "os_version": row.get("os_version"),
            "osVersion": row.get("osVersion"),
            "username": row.get("username"),
            "email": row.get("email"),
        }),
    }


def list_mosyle_devices(limit=100):
    cfg = _settings()

    if not cfg["enabled"]:
        raise ValueError("Mosyle integration is disabled.")

    if not cfg["base_url"] or not cfg["access_token"] or not cfg["username"] or not cfg["password"]:
        raise ValueError("Mosyle integration is missing base URL, access token, username, or password.")

    limit = max(1, min(int(limit), 100))
    bearer = _login(cfg)

    response = requests.post(
        f"{cfg['base_url']}/listdevices",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": bearer,
        },
        json={
            "accessToken": cfg["access_token"],
            "options": {
                "os": "mac",
                "page": 1,
                "page_size": limit,
            },
        },
        timeout=30,
    )

    if not response.ok:
        raise ValueError(
            f"Mosyle listdevices failed: HTTP {response.status_code} - {response.text}"
        )

    payload = response.json()
    rows = _extract_rows(payload)

    devices = []
    for row in rows[:limit]:
        device = _normalize_device(row)
        if device:
            devices.append(device)

    if not devices and rows:
        raise ValueError(f"Mosyle returned rows but no serials were parsed. First row: {rows[0]}")

    return devices