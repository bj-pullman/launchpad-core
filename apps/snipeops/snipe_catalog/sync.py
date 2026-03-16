# apps/snipe_catalog/sync.py
from datetime import datetime, timezone

from apps.snipeops.snipe_catalog.snipe_api import (
    fetch_models,
    fetch_locations,
    fetch_statuslabels,
    fetch_suppliers,
    fetch_depreciations,
)

from apps.snipeops.snipe_catalog.catalog_db import (
    set_meta,
    upsert_models,
    upsert_locations,
    upsert_statuslabels,
    upsert_suppliers,
    upsert_depreciations,
)

def run_full_sync() -> dict:
    """
    Pull reference data from Snipe-IT and store it in the local catalog DB.
    Returns a summary dict.
    """
    try:
        models = fetch_models()
        locations = fetch_locations()
        statuslabels = fetch_statuslabels()
        suppliers = fetch_suppliers()
        depreciations = fetch_depreciations()

        c_models = upsert_models(models)
        c_locations = upsert_locations(locations)
        c_status = upsert_statuslabels(statuslabels)
        c_suppliers = upsert_suppliers(suppliers)
        c_depr = upsert_depreciations(depreciations)

        set_meta("last_sync_utc", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

        return {
            "ok": True,
            "counts": {
                "models": c_models,
                "locations": c_locations,
                "statuslabels": c_status,
                "suppliers": c_suppliers,
                "depreciations": c_depr,
            }
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}