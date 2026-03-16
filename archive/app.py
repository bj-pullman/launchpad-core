# apps/import_by_scan/app.py

from __future__ import annotations

from flask import Blueprint, render_template, request, jsonify
from config import settings
from apps.import_by_scan.profiles import PROFILES
from apps.import_by_scan.snipe import create_asset
from apps.import_by_scan.db import init_db, log_scan, get_recent

bp = Blueprint(
    "import_by_scan",
    __name__,
    url_prefix="/import-by-scan",
    template_folder="templates",
    static_folder="static",
    static_url_path="/import-by-scan/static",
)

# Default profile fallback (so scanning works even if UI doesn't send profile_key)
DEFAULT_PROFILE_KEY = getattr(settings, "DEFAULT_IMPORT_PROFILE_KEY", None) or (
    next(iter(PROFILES.keys()), None) if PROFILES else None
)


def serial_recently_scanned(serial: str, within_last: int = 25) -> bool:
    """
    Serial de-dupe check against our LOCAL SQLite log.
    If the same serial shows up in the last N scans, we treat it as a likely accidental double-scan.
    """
    serial = (serial or "").strip()
    if not serial:
        return False

    recent_rows = get_recent(limit=within_last)
    for r in recent_rows:
        if (r.get("serial") or "").strip().lower() == serial.lower() and r.get("ok") == 1:
            return True
    return False


@bp.get("/")
def index():
    """
    Renders the Import by Scan UI.

    Notes:
    - You may now have a UI that is either "profile-driven" OR "model/defaults-driven".
    - We keep profiles available for backward compatibility.
    """
    recent = get_recent(limit=20)

    # If your newer template expects these, keep them.
    # If you don't use them in the template, they're harmless.
    models = []
    locations = []
    statuses = []
    suppliers = []
    depreciations = []

    # These functions exist in your other snippet; import/use them if present.
    # If you are not using them in this app, you can remove this block safely.
    try:
        from apps.import_by_scan.catalog import (  # type: ignore
            get_models,
            get_locations,
            get_statuslabels,
            get_suppliers,
            get_depreciations,
        )

        models = get_models()
        locations = get_locations()
        statuses = get_statuslabels()
        suppliers = get_suppliers()
        depreciations = get_depreciations()
    except Exception:
        # Catalog lookups are optional depending on your deployment/template.
        pass

    profiles_list = [{"key": k, "name": v.get("display_name", k)} for k, v in PROFILES.items()]

    return render_template(
        "index.html",
        recent=recent,
        models=models,
        locations=locations,
        statuses=statuses,
        suppliers=suppliers,
        depreciations=depreciations,
        profiles=profiles_list,
        default_profile_key=DEFAULT_PROFILE_KEY,
        snipe_url=getattr(settings, "SNIPE_URL", ""),
    )


@bp.get("/recent")
def recent():
    return jsonify({"ok": True, "rows": get_recent(limit=25)})


@bp.post("/scan")
def scan():
    body = request.get_json(silent=True) or {}

    print("=== IMPORT BY SCAN DEBUG ===")
    print("content_type:", request.content_type)
    print("raw_data:", request.get_data(as_text=True))
    print("json_body:", body)
    print("serial_from_body:", body.get("serial"))
    print("============================")

    profile_key = body.get("profile_key")
    serial = (body.get("serial") or "").strip()

    # Accept profile_key, but fall back to a default so the UI doesn't have to send it.
    profile_key = body.get("profile_key") or DEFAULT_PROFILE_KEY
    serial = (body.get("serial") or "").strip()

    if not profile_key or profile_key not in PROFILES:
        return jsonify({"ok": False, "error": "Invalid profile selected."}), 400
    if not serial:
        return jsonify({
            "ok": False,
            "error": "Serial is required.",
            "debug": {
                "content_type": request.content_type,
                "mimetype": request.mimetype,
                "raw": request.get_data(as_text=True),
                "json": body,
                "keys": list(body.keys()),
            }
        }), 400

    # Optional: require model_id (your new UI expects a model selection)
    # Comment this out if you still want profile-only creation without a model.
    if not body.get("model_id"):
        return jsonify({"ok": False, "error": "Model is required."}), 400

    # Local duplicate scan prevention
    if serial_recently_scanned(serial, within_last=25):
        msg = f"Serial '{serial}' was already scanned successfully in the last 25 entries. Likely duplicate scan."
        log_scan(profile_key, serial, ok=False, message=msg)
        return jsonify({"ok": False, "error": msg}), 200

    # Build overrides from the UI
    overrides = {
        "model_id": body.get("model_id"),
        "status_id": body.get("status_id"),
        "location_id": body.get("location_id"),
        "depreciation_id": body.get("depreciation_id"),
        "supplier_id": body.get("supplier_id"),
        "purchase_cost": body.get("purchase_cost"),
        "purchase_date": body.get("purchase_date"),
        "order_number": body.get("order_number"),
        "warranty_months": body.get("warranty_months"),
    }

    # Drop empties so we don't send junk to Snipe-IT
    overrides = {k: v for k, v in overrides.items() if v not in (None, "", "null")}

    # Merge overrides into the chosen profile (backward compatible with create_asset(profile, serial))
    profile = dict(PROFILES[profile_key])
    profile.update(overrides)

    # Create in Snipe-IT
    result = create_asset(profile, serial)
    data = result.get("data") or {}

    # Your create_asset wrapper appears to return {"data": {...}} with a "status" field
    if data.get("status") != "success":
        msg = str(data.get("messages", data))
        log_scan(profile_key, serial, ok=False, message=msg)
        return jsonify({"ok": False, "error": data.get("messages", data), "raw": data}), 200

    payload = data.get("payload") or {}
    asset_id = payload.get("id")
    asset_tag = payload.get("asset_tag")
    asset_url = f"{settings.SNIPE_URL}/hardware/{asset_id}" if asset_id else None

    log_scan(
        profile_key,
        serial,
        ok=True,
        asset_id=asset_id,
        asset_tag=asset_tag,
        asset_url=asset_url,
        message="created",
    )

    return jsonify({"ok": True, "asset_id": asset_id, "asset_tag": asset_tag, "asset_url": asset_url}), 200