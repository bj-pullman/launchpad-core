import requests
import urllib3
from config import settings

from apps.snipeops.import_by_scan.serial_utils import serial_candidates, normalize_serial

# Only silence warnings if you're intentionally not verifying SSL
if settings.VERIFY_SSL is False:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _headers():
    return {
        "Authorization": f"Bearer {settings.API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def find_asset_by_serial(raw_serial: str) -> dict | None:
    """
    Search Snipe-IT for an asset matching this serial (case-insensitive exact match).
    Returns a row dict (with id/asset_tag/serial/etc) if found, else None.
    """
    candidates = serial_candidates(raw_serial)
    if not candidates:
        return None

    url = f"{settings.SNIPE_URL}/api/v1/hardware"

    # Try each candidate until we find an exact serial match
    for cand in candidates:
        resp = requests.get(
            url,
            headers=_headers(),
            params={"search": cand},
            verify=settings.VERIFY_SSL,
            timeout=30,
        )

        try:
            data = resp.json()
        except Exception:
            continue

        rows = data.get("rows") or []
        cand_u = cand.upper()

        for r in rows:
            r_serial = normalize_serial(r.get("serial") or "")
            if r_serial == cand_u:
                return r

    return None


def create_asset(profile: dict, serial: str) -> dict:
    """
    Creates an asset in Snipe-IT using the profile defaults + scanned serial.
    Returns dict: {"http_status": int, "data": json}
    """
    url = f"{settings.SNIPE_URL}/api/v1/hardware"

    payload = {
        "serial": (serial or "").strip(),
        "model_id": profile["model_id"],
        "status_id": profile["status_id"],
    }

    # Optional fields (only if present)
    if profile.get("location_id"):
        payload["location_id"] = profile["location_id"]

    if profile.get("supplier_id"):
        payload["supplier_id"] = profile["supplier_id"]

    if profile.get("depreciation_id"):
        payload["depreciation_id"] = profile["depreciation_id"]

    if profile.get("purchase_cost") is not None:
        payload["purchase_cost"] = profile["purchase_cost"]

    if profile.get("purchase_date"):
        payload["purchase_date"] = profile["purchase_date"]

    if profile.get("order_number"):
        payload["order_number"] = profile["order_number"]

    if profile.get("warranty_months") is not None:
        payload["warranty_months"] = profile["warranty_months"]

    if profile.get("asset_tag"):
        payload["asset_tag"] = profile["asset_tag"]

    # Notes (batch tracking)
    notes_prefix = profile.get("notes_prefix")
    if notes_prefix:
        payload["notes"] = f"{notes_prefix} | Serial scanned"

    # Custom fields (if you use them)
    custom_fields = profile.get("custom_fields") or {}
    payload.update(custom_fields)

    resp = requests.post(
        url,
        headers=_headers(),
        json=payload,
        verify=settings.VERIFY_SSL,
        timeout=30
    )

    return {"http_status": resp.status_code, "data": resp.json()}

def find_asset_by_asset_tag(tag: str) -> dict | None:
    tag = (tag or "").strip()
    if not tag:
        return None

    url = f"{settings.SNIPE_URL}/api/v1/hardware"
    resp = requests.get(
        url,
        headers=_headers(),
        params={"search": tag},
        verify=settings.VERIFY_SSL,
        timeout=30,
    )

    data = resp.json() if resp.content else {}
    rows = data.get("rows") or []
    for r in rows:
        if (r.get("asset_tag") or "").strip() == tag:
            return r
    return None