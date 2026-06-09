# apps/snipe_catalog/sync.py
from datetime import datetime, timezone

from apps.snipeops.snipe_catalog.snipe_api import (
    fetch_models,
    fetch_locations,
    fetch_statuslabels,
    fetch_suppliers,
    fetch_depreciations,
    fetch_categories,
    fetch_manufacturers,
    fetch_assets,
)

from apps.snipeops.snipe_catalog.catalog_db import (
    set_meta,
    upsert_models,
    upsert_locations,
    upsert_statuslabels,
    upsert_suppliers,
    upsert_depreciations,
    upsert_categories,
    upsert_manufacturers,
    upsert_assets,
)

def run_full_sync() -> dict:
    counts = {}

    try:
        models = fetch_models()
        counts["models"] = upsert_models(models)

        locations = fetch_locations()
        counts["locations"] = upsert_locations(locations)

        statuslabels = fetch_statuslabels()
        counts["statuslabels"] = upsert_statuslabels(statuslabels)

        suppliers = fetch_suppliers()
        counts["suppliers"] = upsert_suppliers(suppliers)

        depreciations = fetch_depreciations()
        counts["depreciations"] = upsert_depreciations(depreciations)

        categories = fetch_categories()
        counts["categories"] = upsert_categories(categories)

        manufacturers = fetch_manufacturers()
        counts["manufacturers"] = upsert_manufacturers(manufacturers)

        assets = fetch_assets()
        counts["assets"] = upsert_assets(assets)

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        set_meta("last_sync_utc", now)

        return {
            "ok": True,
            "last_sync_utc": now,
            "counts": counts,
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "counts": counts,
        }