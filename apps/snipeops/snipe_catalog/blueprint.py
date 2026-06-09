from collections import Counter

from flask import Blueprint, render_template, jsonify, request

from modules.core.auth.decorators import login_required, require_permission

from apps.snipeops.snipe_catalog.catalog_db import (
    init_db,
    get_meta,
    list_table,
)
from apps.snipeops.snipe_catalog.sync import run_full_sync
from apps.snipeops.snipe_catalog.snipe_api import create_model
from apps.snipeops.mapping_service import list_mappings, upsert_mapping
from apps.snipeops.connectors.intune_client import list_intune_devices
from apps.snipeops.connectors.mosyle_client import list_mosyle_devices
from apps.snipeops.snipe_catalog.cleanup_service import (
    build_model_cleanup_queue,
    preview_model_merge,
    rename_model,
    merge_models,
)

bp = Blueprint(
    "snipe_catalog",
    __name__,
    url_prefix="/snipe-catalog",
    template_folder="templates",
    static_folder="static",
)

init_db()


def _norm(value):
    return str(value or "").strip()


def _model_display(model):
    name = _norm(model.get("name"))
    model_number = _norm(model.get("model_number"))

    if name and model_number:
        return f"{name} — {model_number}"

    return name or model_number


def _discover_source_models(source, limit):
    if source == "mosyle":
        devices = list_mosyle_devices(limit=limit)
    else:
        devices = list_intune_devices(limit=limit)

    counts = Counter()

    for device in devices:
        raw_model = _norm(device.get("model"))
        if raw_model:
            counts[raw_model] += 1

    existing_mappings = {
        _norm(item.get("raw_value")).lower(): item
        for item in list_mappings(field="model", source=source)
    }

    rows = []
    for raw_value, count in counts.most_common():
        mapping = existing_mappings.get(raw_value.lower())

        rows.append({
            "source": source,
            "raw_value": raw_value,
            "count": count,
            "mapped_value": mapping.get("mapped_value") if mapping else "",
            "mapping_id": mapping.get("id") if mapping else None,
        })

    return rows


@bp.get("/")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def index():
    last_sync = get_meta("last_sync_utc", "")
    return render_template("snipe_catalog/index.html", last_sync=last_sync)


@bp.post("/sync")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def sync_now():
    result = run_full_sync()
    return jsonify(result), (200 if result.get("ok") else 500)


@bp.get("/api/models")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_models():
    return jsonify({"ok": True, "rows": list_table("catalog_models")})


@bp.get("/api/locations")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_locations():
    return jsonify({"ok": True, "rows": list_table("catalog_locations")})


@bp.get("/api/statuslabels")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_statuslabels():
    return jsonify({"ok": True, "rows": list_table("catalog_statuslabels")})


@bp.get("/api/suppliers")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_suppliers():
    return jsonify({"ok": True, "rows": list_table("catalog_suppliers")})


@bp.get("/api/depreciations")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_depreciations():
    return jsonify({"ok": True, "rows": list_table("catalog_depreciations")})


@bp.get("/api/model-mappings")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_model_mappings():
    source = _norm(request.args.get("source")).lower() or "intune"
    limit_raw = _norm(request.args.get("limit")).lower()

    try:
        limit = None if limit_raw in {"", "all"} else max(1, min(int(limit_raw), 5000))
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid discovery limit."}), 400

    if source not in {"intune", "mosyle"}:
        return jsonify({"ok": False, "error": "Invalid source."}), 400

    try:
        discovered = _discover_source_models(source, limit)

        models = list_table("catalog_models")
        categories = list_table("catalog_categories")
        manufacturers = list_table("catalog_manufacturers")

        return jsonify({
            "ok": True,
            "source": source,
            "limit": limit,
            "rows": discovered,
            "models": [
                {
                    "id": model.get("id"),
                    "name": model.get("name"),
                    "model_number": model.get("model_number"),
                    "manufacturer_name": model.get("manufacturer_name"),
                    "display": _model_display(model),
                }
                for model in models
            ],
            "categories": [
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                }
                for row in categories
            ],

            "manufacturers": [
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                }
                for row in manufacturers
            ],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.post("/api/model-mappings")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def save_model_mappings():
    payload = request.get_json(silent=True) or {}
    source = _norm(payload.get("source")).lower()
    mappings = payload.get("mappings") or []

    if source not in {"intune", "mosyle"}:
        return jsonify({"ok": False, "error": "Invalid source."}), 400

    saved = []

    try:
        for item in mappings:
            raw_value = _norm(item.get("raw_value"))
            mapped_value = _norm(item.get("mapped_value"))

            if not raw_value or not mapped_value:
                continue

            saved.append(
                upsert_mapping(
                    source=source,
                    field="model",
                    raw_value=raw_value,
                    mapped_value=mapped_value,
                    notes="Managed from Snipe Catalog model mapping.",
                )
            )

        return jsonify({
            "ok": True,
            "saved": len(saved),
            "message": f"Saved {len(saved)} model mapping(s).",
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    
@bp.post("/api/models")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def create_snipe_model():
    payload = request.get_json(silent=True) or {}

    name = _norm(payload.get("name"))
    model_number = _norm(payload.get("model_number"))
    category_id = payload.get("category_id")
    manufacturer_id = payload.get("manufacturer_id")

    if not name:
        return jsonify({"ok": False, "error": "Model name is required."}), 400

    if not category_id:
        return jsonify({"ok": False, "error": "Category is required to create a Snipe model."}), 400

    try:
        result = create_model(
            name=name,
            category_id=category_id,
            manufacturer_id=manufacturer_id,
            model_number=model_number,
        )

        # Refresh model catalog after create so dropdowns can use it.
        run_full_sync()

        return jsonify({
            "ok": True,
            "message": f"Created Snipe model: {name}",
            "result": result,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    
@bp.get("/api/categories")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_categories():
    return jsonify({"ok": True, "rows": list_table("catalog_categories")})


@bp.get("/api/manufacturers")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_manufacturers():
    return jsonify({"ok": True, "rows": list_table("catalog_manufacturers")})
    
@bp.get("/api/cleanup/models")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_cleanup_models():
    try:
        min_score = int(request.args.get("min_score") or 92)
        return jsonify(build_model_cleanup_queue(min_score=min_score))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.post("/api/cleanup/models/preview-merge")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_cleanup_models_preview_merge():
    payload = request.get_json(silent=True) or {}

    try:
        result = preview_model_merge(
            keeper_model_id=payload.get("keeper_model_id"),
            source_model_ids=payload.get("source_model_ids") or [],
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@bp.post("/api/cleanup/models/rename")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_cleanup_models_rename():
    payload = request.get_json(silent=True) or {}

    try:
        result = rename_model(
            model_id=payload.get("model_id"),
            name=payload.get("name"),
            model_number=payload.get("model_number"),
            manufacturer_id=payload.get("manufacturer_id"),
            category_id=payload.get("category_id"),
        )

        run_full_sync()

        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@bp.post("/api/cleanup/models/merge")
@login_required
@require_permission("snipeops.snipe_catalog.view")
def api_cleanup_models_merge():
    payload = request.get_json(silent=True) or {}

    confirmation = _norm(payload.get("confirmation"))
    delete_source_models = bool(payload.get("delete_source_models"))

    if delete_source_models and confirmation != "DELETE SOURCE MODELS":
        return jsonify({
            "ok": False,
            "error": "Deletion requires confirmation text: DELETE SOURCE MODELS",
        }), 400

    try:
        result = merge_models(
            keeper_model_id=payload.get("keeper_model_id"),
            source_model_ids=payload.get("source_model_ids") or [],
            keeper_updates=payload.get("keeper_updates") or {},
            delete_source_models=delete_source_models,
        )

        run_full_sync()

        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400