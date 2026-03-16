from __future__ import annotations

import re

from flask import Blueprint, render_template, request, jsonify
from config import settings

from modules.core.auth.decorators import login_required, require_permission

from apps.snipeops.import_by_scan.snipe import create_asset, find_asset_by_serial, find_asset_by_asset_tag
from apps.snipeops.import_by_scan.db import log_scan, get_recent
from apps.snipeops.import_by_scan.serial_utils import normalize_serial
from apps.snipeops.snipe_catalog.catalog_reader import (
    get_models, get_locations, get_statuslabels, get_suppliers, get_depreciations
)

bp = Blueprint(
    "import_by_scan",
    __name__,
    url_prefix="/import-by-scan",
    template_folder="templates",
    static_folder="static",
)

@bp.get("/")
@login_required
@require_permission("snipeops.import_by_scan.view")
def index():
    recent = get_recent(limit=20)

    return render_template(
        "import_by_scan/index.html",
        recent=recent,
        models=get_models(),
        locations=get_locations(),
        statuses=get_statuslabels(),
        suppliers=get_suppliers(),
        depreciations=get_depreciations(),
    )

def _get_body() -> dict:
    body = request.get_json(silent=True)
    if isinstance(body, dict) and body:
        return body
    return request.form.to_dict(flat=True)

def _to_int(v) -> int:
    try:
        return int(v)
    except Exception:
        return 0

@bp.post("/scan")
@login_required
@require_permission("snipeops.import_by_scan.view")
def scan():
    body = _get_body()

    serial_raw = (body.get("serial") or "").strip()
    serial = normalize_serial(serial_raw) if serial_raw else ""
    if not serial:
        return jsonify({"ok": False, "error": "Serial is required."}), 400

    asset_tag = (body.get("asset_tag") or "").strip() or None
    if asset_tag is not None:
        if not re.fullmatch(r"\d{6}", asset_tag):
            return jsonify({
                "ok": False,
                "error": "ERROR: Asset tag must be blank or a 6-digit number (e.g. 123456)."
            }), 400

    model_id = _to_int(body.get("model_id"))
    status_id = _to_int(body.get("status_id"))
    location_id = _to_int(body.get("location_id"))

    supplier_id = _to_int(body.get("supplier_id")) or None
    depreciation_id = _to_int(body.get("depreciation_id")) or None

    if not model_id or not status_id or not location_id:
        return jsonify({"ok": False, "error": "Model, Status, and Location are required selections."}), 400

    existing = find_asset_by_serial(serial)
    if existing:
        existing_id = existing.get("id")
        existing_tag = existing.get("asset_tag")
        existing_url = f"{settings.SNIPE_URL}/hardware/{existing_id}" if existing_id else None

        msg = "ERROR: Duplicate Serial"
        meta = log_scan(
            "ui",
            serial,
            ok=False,
            asset_id=existing_id,
            asset_tag=existing_tag,
            asset_url=existing_url,
            message=msg,
        )

        return jsonify({
            "ok": False,
            "error": msg,
            "message": msg,
            "asset_id": existing_id,
            "asset_tag": existing_tag,
            "asset_url": existing_url,
            "timestamp": meta.get("created_at"),
            "timestamp_display": meta.get("created_at"),
        }), 200
    
    if asset_tag:
        existing_tag = find_asset_by_asset_tag(asset_tag)
        if existing_tag:
            existing_id = existing_tag.get("id")
            existing_url = f"{settings.SNIPE_URL}/hardware/{existing_id}" if existing_id else None
            msg = "ERROR: Duplicate Asset Tag"
            meta = log_scan("ui", serial, ok=False, asset_id=existing_id,
                            asset_tag=asset_tag, asset_url=existing_url, message=msg)
            return jsonify({
                "ok": False,
                "error": msg,
                "message": msg,
                "asset_id": existing_id,
                "asset_tag": asset_tag,
                "asset_url": existing_url,
                "timestamp": meta.get("created_at"),
                "timestamp_display": meta.get("created_at"),
            }), 200

    purchase_cost = (body.get("purchase_cost") or "").strip()
    purchase_date = (body.get("purchase_date") or "").strip() or None
    order_number = (body.get("order_number") or "").strip() or None
    warranty_months = (body.get("warranty_months") or "").strip()

    profile = {
        "model_id": model_id,
        "status_id": status_id,
        "location_id": location_id,
    }
    if supplier_id:
        profile["supplier_id"] = supplier_id
    if depreciation_id:
        profile["depreciation_id"] = depreciation_id

    if purchase_cost != "":
        try:
            profile["purchase_cost"] = float(purchase_cost)
        except Exception:
            pass

    if purchase_date:
        profile["purchase_date"] = purchase_date
    if order_number:
        profile["order_number"] = order_number

    if warranty_months != "":
        try:
            profile["warranty_months"] = int(warranty_months)
        except Exception:
            pass

    if asset_tag:
        profile["asset_tag"] = asset_tag

    result = create_asset(profile, serial)
    data = result.get("data") or {}

    if data.get("status") != "success":
        msg = data.get("messages") or data.get("message") or str(data)
        msg = f"ERROR: {msg}"

        meta = log_scan("ui", serial, ok=False, message=str(msg))

        return jsonify({
            "ok": False,
            "error": str(msg),
            "message": str(msg),
            "timestamp": meta.get("created_at"),
            "timestamp_display": meta.get("created_at"),
            "raw": data,
        }), 200

    payload = data.get("payload") or {}
    asset_id = payload.get("id")
    asset_tag = payload.get("asset_tag")
    asset_url = f"{settings.SNIPE_URL}/hardware/{asset_id}" if asset_id else None

    meta = log_scan(
        "ui",
        serial,
        ok=True,
        asset_id=asset_id,
        asset_tag=asset_tag,
        asset_url=asset_url,
        message="Created",
    )

    return jsonify({
        "ok": True,
        "asset_id": asset_id,
        "asset_tag": asset_tag,
        "asset_url": asset_url,
        "message": "Created",
        "timestamp": meta.get("created_at"),
        "timestamp_display": meta.get("created_at"),
    }), 200