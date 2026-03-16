import requests
from config import settings

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def get_paginated(endpoint: str, limit: int = 500) -> list[dict]:

    # Pulls ALL rows from a Snipe endpoint that returns {rows:[], total:...}.
    # Example endpoints:
    #   /api/v1/models
    #   /api/v1/locations
    #   /api/v1/statuslabels
    #   /api/v1/suppliers
    #   /api/v1/depreciations

    out: list[dict] = []
    offset = 0

    while True:
        url = f"{settings.SNIPE_URL}{endpoint}?limit={limit}&offset={offset}"
        res = requests.get(url, headers=_headers(), verify=settings.VERIFY_SSL, timeout=30)
        res.raise_for_status()
        data = res.json()
        rows = data.get("rows") or []
        out.extend(rows)

        total = data.get("total")
        if total is None:
            # fallback if total missing
            if not rows:
                break
        if total is not None and len(out) >= int(total):
            break

        offset += limit

    return out

# ---- Friendly wrappers used by sync.py ----
def fetch_models() -> list[dict]:
    return get_paginated("/api/v1/models")


def fetch_locations() -> list[dict]:
    return get_paginated("/api/v1/locations")


def fetch_statuslabels() -> list[dict]:
    return get_paginated("/api/v1/statuslabels")


def fetch_suppliers() -> list[dict]:
    return get_paginated("/api/v1/suppliers")


def fetch_depreciations() -> list[dict]:
    return get_paginated("/api/v1/depreciations")