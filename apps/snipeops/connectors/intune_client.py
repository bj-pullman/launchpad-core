import requests

from modules.core.settings.settings_service import get_setting, get_bool_setting
from apps.snipeops.import_by_scan.serial_utils import normalize_serial


def _settings():
    return {
        "enabled": get_bool_setting("integrations.microsoft.intune.enabled", False),
        "tenant_id": (get_setting("integrations.microsoft.intune.tenant_id", "") or "").strip(),
        "client_id": (get_setting("integrations.microsoft.intune.client_id", "") or "").strip(),
        "client_secret": (get_setting("integrations.microsoft.intune.client_secret", "") or "").strip(),
        "graph_base_url": (
            get_setting(
                "integrations.microsoft.intune.graph_base_url",
                "https://graph.microsoft.com/v1.0",
            )
            or "https://graph.microsoft.com/v1.0"
        ).strip().rstrip("/"),
    }


def get_intune_token():
    cfg = _settings()

    if not cfg["enabled"]:
        raise ValueError("Intune integration is disabled.")

    missing = [
        key
        for key in ("tenant_id", "client_id", "client_secret")
        if not cfg[key]
    ]
    if missing:
        raise ValueError(f"Intune integration is missing: {', '.join(missing)}")

    url = f"https://login.microsoftonline.com/{cfg['tenant_id']}/oauth2/v2.0/token"

    response = requests.post(
        url,
        data={
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    response.raise_for_status()

    return response.json()["access_token"]


def list_intune_devices(limit=100):
    cfg = _settings()
    token = get_intune_token()

    url = (
        f"{cfg['graph_base_url']}/deviceManagement/managedDevices"
        "?$select=id,deviceName,serialNumber,manufacturer,model,operatingSystem,osVersion,userPrincipalName,azureADDeviceId,lastSyncDateTime"
        f"&$top={int(limit)}"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    devices = []

    while url and len(devices) < limit:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()

        for row in payload.get("value", []):
            serial = normalize_serial(row.get("serialNumber"))
            if not serial:
                continue

            devices.append({
                "source": "intune",
                "source_id": row.get("id"),
                "name": row.get("deviceName") or "",
                "serial": serial,
                "raw_serial": row.get("serialNumber") or "",
                "manufacturer": row.get("manufacturer") or "",
                "model": row.get("model") or "",
                "os": row.get("operatingSystem") or "",
                "os_version": row.get("osVersion") or "",
                "assigned_user": row.get("userPrincipalName") or "",
                "last_seen": row.get("lastSyncDateTime") or "",
            })

            if len(devices) >= limit:
                break

        url = payload.get("@odata.nextLink")

    return devices