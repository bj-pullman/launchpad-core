from apps.snipeops.snipe_catalog.catalog_db import list_table

def get_models():
    rows = list_table("catalog_models")
    return [{"id": r["id"], "name": r["name"], "manufacturer_name": r.get("manufacturer_name"), "model_number": r.get("model_number")} for r in rows]

def get_locations():
    rows = list_table("catalog_locations")
    return [{"id": r["id"], "name": r["name"]} for r in rows]

def get_statuslabels():
    rows = list_table("catalog_statuslabels")
    return [{"id": r["id"], "name": r["name"]} for r in rows]

def get_suppliers():
    rows = list_table("catalog_suppliers")
    return [{"id": r["id"], "name": r["name"]} for r in rows]

def get_depreciations():
    rows = list_table("catalog_depreciations")
    return [{"id": r["id"], "name": r["name"]} for r in rows]