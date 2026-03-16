from flask import Blueprint, render_template, jsonify

from modules.core.auth.decorators import login_required, require_permission

from apps.snipeops.snipe_catalog.catalog_db import (
    init_db, set_meta, get_meta,
    upsert_models, upsert_locations, upsert_statuslabels, upsert_suppliers, upsert_depreciations,
    list_table,
)
from apps.snipeops.snipe_catalog.snipe_api import get_paginated
from apps.snipeops.snipe_catalog.sync import run_full_sync

bp = Blueprint(
    "snipe_catalog",
    __name__,
    url_prefix="/snipe-catalog",
    template_folder="templates",
    static_folder="static",
)

init_db()


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