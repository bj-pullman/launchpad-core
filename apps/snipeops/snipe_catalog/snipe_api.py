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

    verify_ssl = env_verify_ssl if db_verify_ssl is None else _to_bool(db_verify_ssl, True)

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


def _url(endpoint):
    settings = _get_snipeops_settings()
    base_url = settings["base_url"]

    if not base_url:
        raise ValueError("SnipeOps base URL is missing from settings.")

    return f"{base_url.rstrip('/')}{endpoint}"


def _request(method, endpoint, payload=None, timeout=30):
    settings = _get_snipeops_settings()

    response = requests.request(
        method,
        _url(endpoint),
        headers=_headers(),
        verify=settings["verify_ssl"],
        timeout=timeout,
        json=payload,
    )

    try:
        data = response.json()
    except Exception:
        data = {"raw_response": response.text}

    if not response.ok:
        raise ValueError({
            "status_code": response.status_code,
            "endpoint": endpoint,
            "response": data,
        })

    if isinstance(data, dict) and data.get("status") == "error":
        raise ValueError({
            "endpoint": endpoint,
            "response": data,
        })

    return data


def get_paginated(endpoint, limit=250):
    import time

    settings = _get_snipeops_settings()
    out = []
    offset = 0

    while True:
        url = f"{_url(endpoint)}?limit={limit}&offset={offset}"
        payload = None
        last_error = None

        for attempt in range(1, 4):
            try:
                response = requests.get(
                    url,
                    headers=_headers(),
                    verify=settings["verify_ssl"],
                    timeout=45,
                )

                response.raise_for_status()
                payload = response.json()
                break

            except Exception as exc:
                last_error = exc
                time.sleep(attempt * 2)

        if payload is None:
            raise RuntimeError(f"Snipe-IT request failed at offset {offset}: {last_error}")

        rows = payload.get("rows") or []
        out.extend(rows)

        total = payload.get("total")

        if total is not None and len(out) >= int(total):
            break

        if not rows:
            break

        offset += limit
        time.sleep(0.5)

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


def fetch_categories():
    return get_paginated("/api/v1/categories")


def fetch_manufacturers():
    return get_paginated("/api/v1/manufacturers")


def fetch_assets():
    return get_paginated("/api/v1/hardware", limit=250)

def post_json(endpoint, payload):
    return _request("POST", endpoint, payload)


def patch_json(endpoint, payload):
    return _request("PATCH", endpoint, payload)


def put_json(endpoint, payload):
    return _request("PUT", endpoint, payload)


def delete_json(endpoint):
    return _request("DELETE", endpoint)


def create_model(name, category_id, manufacturer_id=None, model_number=None):
    payload = {
        "name": str(name or "").strip(),
        "category_id": int(category_id),
    }

    if manufacturer_id:
        payload["manufacturer_id"] = int(manufacturer_id)

    if model_number:
        payload["model_number"] = str(model_number).strip()

    if not payload["name"]:
        raise ValueError("Model name is required.")

    return post_json("/api/v1/models", payload)


def update_model(model_id, name=None, category_id=None, manufacturer_id=None, model_number=None):
    payload = {}

    if name is not None:
        payload["name"] = str(name or "").strip()

    if category_id:
        payload["category_id"] = int(category_id)

    if manufacturer_id:
        payload["manufacturer_id"] = int(manufacturer_id)

    if model_number is not None:
        payload["model_number"] = str(model_number or "").strip()

    if not payload:
        return {"status": "skipped", "message": "No model updates supplied."}

    return patch_json(f"/api/v1/models/{int(model_id)}", payload)


def update_asset_model(asset_id, model_id):
    return patch_json(
        f"/api/v1/hardware/{int(asset_id)}",
        {"model_id": int(model_id)},
    )


def delete_model(model_id):
    return delete_json(f"/api/v1/models/{int(model_id)}")