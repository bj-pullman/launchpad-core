from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from modules.core.auth.decorators import login_required, require_permission

from apps.snipeops.snipe_catalog.catalog_db import (
    get_asset,
    search_assets,
    get_assets_assigned_to_asset,
)

from apps.snipeops.checkout_assets.checkout_assets_db import (
    get_recent,
    log_checkout,
)

from apps.snipeops.checkout_assets.snipe import (
    build_asset_url,
    checkout_asset_to_asset,
    checkin_asset,
    update_asset_tag,
)


bp = Blueprint(
    "checkout_assets",
    __name__,
    url_prefix="/checkout-assets",
    template_folder="templates",
    static_folder="static",
)


def _get_body() -> dict:
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    return request.form.to_dict(flat=True)


def _asset_payload(asset: dict | None) -> dict | None:
    if not asset:
        return None

    return {
        "id": asset.get("id"),
        "asset_tag": asset.get("asset_tag") or "",
        "serial": asset.get("serial") or "",
        "name": asset.get("name") or "",
        "model_name": asset.get("model_name") or "",
        "status_name": asset.get("status_name") or "",
        "location_name": asset.get("location_name") or "",
        "assigned_type": asset.get("assigned_type") or "",
        "assigned_name": asset.get("assigned_name") or "",
        "asset_url": build_asset_url(asset.get("id")),
    }


@bp.get("/")
@login_required
@require_permission("snipeops.checkout_assets.view")
def index():
    return render_template(
        "checkout_assets/index.html",
        recent=get_recent(limit=50),
    )


@bp.get("/api/search")
@login_required
@require_permission("snipeops.checkout_assets.view")
def api_search():
    query = (request.args.get("q") or "").strip()
    limit = int(request.args.get("limit") or 25)

    rows = search_assets(query, limit=min(max(limit, 1), 100))

    return jsonify({
        "ok": True,
        "results": [_asset_payload(row) for row in rows],
    })


@bp.get("/api/assets/<int:asset_id>")
@login_required
@require_permission("snipeops.checkout_assets.view")
def api_get_asset(asset_id: int):
    asset = get_asset(asset_id)

    if not asset:
        return jsonify({"ok": False, "error": "Asset not found in SnipeOps Catalog."}), 404

    return jsonify({
        "ok": True,
        "asset": _asset_payload(asset),
    })


@bp.post("/api/checkout")
@login_required
@require_permission("snipeops.checkout_assets.manage")
def api_checkout():
    body = _get_body()

    parent_asset_id = body.get("parent_asset_id")
    child_asset_ids = body.get("child_asset_ids") or []
    delay_ms = int(body.get("delay_ms") or 350)

    delay_ms = min(max(delay_ms, 0), 5000)
    delay_seconds = delay_ms / 1000

    if not parent_asset_id:
        return jsonify({"ok": False, "error": "Parent asset is required."}), 400

    if not isinstance(child_asset_ids, list) or not child_asset_ids:
        return jsonify({"ok": False, "error": "Select at least one child asset."}), 400

    parent_asset = get_asset(int(parent_asset_id))
    if not parent_asset:
        return jsonify({"ok": False, "error": "Parent asset not found in SnipeOps Catalog."}), 404

    results = []

    for raw_child_id in child_asset_ids:
        try:
            child_asset_id = int(raw_child_id)
            child_asset = get_asset(child_asset_id)

            if not child_asset:
                message = "Child asset not found in SnipeOps Catalog."
                meta = log_checkout(
                    parent_asset=parent_asset,
                    child_asset={"id": child_asset_id},
                    ok=False,
                    message=message,
                )
                results.append({
                    "ok": False,
                    "child_asset_id": child_asset_id,
                    "message": message,
                    "created_at": meta["created_at"],
                })
                continue

            if int(parent_asset["id"]) == int(child_asset["id"]):
                message = "Cannot check an asset out to itself."
                meta = log_checkout(
                    parent_asset=parent_asset,
                    child_asset=child_asset,
                    ok=False,
                    message=message,
                )
                results.append({
                    "ok": False,
                    "child_asset": _asset_payload(child_asset),
                    "message": message,
                    "created_at": meta["created_at"],
                })
                continue

            checkout_asset_to_asset(
                child_asset_id=int(child_asset["id"]),
                parent_asset_id=int(parent_asset["id"]),
                delay_seconds=delay_seconds,
            )

            message = "Checked out to parent asset."
            meta = log_checkout(
                parent_asset=parent_asset,
                child_asset=child_asset,
                ok=True,
                message=message,
            )

            results.append({
                "ok": True,
                "parent_asset": _asset_payload(parent_asset),
                "child_asset": _asset_payload(child_asset),
                "message": message,
                "created_at": meta["created_at"],
            })

        except Exception as exc:
            child_asset = None
            try:
                child_asset = get_asset(int(raw_child_id))
            except Exception:
                pass

            message = str(exc)
            meta = log_checkout(
                parent_asset=parent_asset,
                child_asset=child_asset,
                ok=False,
                message=message,
            )

            results.append({
                "ok": False,
                "child_asset": _asset_payload(child_asset),
                "message": message,
                "created_at": meta["created_at"],
            })

    return jsonify({
        "ok": True,
        "parent_asset": _asset_payload(parent_asset),
        "results": results,
    })

@bp.post("/api/checkin-parent-children")
@login_required
@require_permission("snipeops.checkout_assets.manage")
def api_checkin_parent_children():
    body = _get_body()

    try:
        parent_asset_id = int(body.get("parent_asset_id") or 0)
        delay_ms = int(body.get("delay_ms") or 350)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid parent asset id."}), 400

    delay_ms = min(max(delay_ms, 0), 5000)
    delay_seconds = delay_ms / 1000

    parent_asset = get_asset(parent_asset_id)

    if not parent_asset:
        return jsonify({"ok": False, "error": "Parent asset not found in SnipeOps Catalog."}), 404

    child_assets = get_assets_assigned_to_asset(parent_asset_id)

    if not child_assets:
        return jsonify({
            "ok": True,
            "parent_asset": _asset_payload(parent_asset),
            "results": [],
            "message": "No child assets are currently assigned to this parent in the local catalog.",
        })

    results = []

    for child_asset in child_assets:
        try:
            checkin_asset(
                asset_id=int(child_asset["id"]),
                note=f"Bulk checked in from parent asset {parent_asset.get('asset_tag') or parent_asset.get('name')} by SnipeOps Checkout Assets.",
                delay_seconds=delay_seconds,
            )

            message = "Checked in from parent asset."
            meta = log_checkout(
                parent_asset=parent_asset,
                child_asset=child_asset,
                ok=True,
                message=message,
            )

            results.append({
                "ok": True,
                "parent_asset": _asset_payload(parent_asset),
                "child_asset": _asset_payload(child_asset),
                "message": message,
                "created_at": meta["created_at"],
            })

        except Exception as exc:
            message = str(exc)
            meta = log_checkout(
                parent_asset=parent_asset,
                child_asset=child_asset,
                ok=False,
                message=message,
            )

            results.append({
                "ok": False,
                "parent_asset": _asset_payload(parent_asset),
                "child_asset": _asset_payload(child_asset),
                "message": message,
                "created_at": meta["created_at"],
            })

    return jsonify({
        "ok": True,
        "parent_asset": _asset_payload(parent_asset),
        "results": results,
    })

@bp.get("/api/parent-children-count")
@login_required
@require_permission("snipeops.checkout_assets.view")
def api_parent_children_count():
    try:
        parent_asset_id = int(request.args.get("parent_asset_id") or 0)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid parent asset id."}), 400

    parent_asset = get_asset(parent_asset_id)
    if not parent_asset:
        return jsonify({"ok": False, "error": "Parent asset not found in SnipeOps Catalog."}), 404

    child_assets = get_assets_assigned_to_asset(parent_asset_id)

    return jsonify({
        "ok": True,
        "count": len(child_assets),
    })

@bp.post("/api/assets/<int:asset_id>/asset-tag")
@login_required
@require_permission("snipeops.checkout_assets.manage")
def api_update_asset_tag(asset_id: int):
    body = _get_body()
    asset_tag = (body.get("asset_tag") or "").strip()

    if not asset_tag:
        return jsonify({"ok": False, "error": "Asset number is required."}), 400

    asset = get_asset(asset_id)
    if not asset:
        return jsonify({"ok": False, "error": "Asset not found in SnipeOps Catalog."}), 404

    try:
        update_asset_tag(asset_id=asset_id, asset_tag=asset_tag)
        refreshed = get_asset(asset_id) or {**asset, "asset_tag": asset_tag}

        return jsonify({
            "ok": True,
            "asset": _asset_payload(refreshed),
            "message": "Asset number updated.",
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    
    
@bp.post("/api/assets/<int:asset_id>/checkin")
@login_required
@require_permission("snipeops.checkout_assets.manage")
def api_checkin_single_asset(asset_id: int):
    body = _get_body()
    delay_ms = int(body.get("delay_ms") or 350)
    delay_ms = min(max(delay_ms, 0), 5000)

    child_asset = get_asset(asset_id)
    if not child_asset:
        return jsonify({"ok": False, "error": "Asset not found in SnipeOps Catalog."}), 404

    try:
        checkin_asset(
            asset_id=asset_id,
            note="Checked in by SnipeOps Checkout Assets.",
            delay_seconds=delay_ms / 1000,
        )

        meta = log_checkout(
            parent_asset={},
            child_asset=child_asset,
            ok=True,
            message="Checked in.",
        )

        return jsonify({
            "ok": True,
            "child_asset": _asset_payload(child_asset),
            "message": "Checked in.",
            "created_at": meta["created_at"],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    

@bp.get("/api/assets/<int:asset_id>/children")
@login_required
@require_permission("snipeops.checkout_assets.view")
def api_get_parent_children(asset_id: int):
    parent_asset = get_asset(asset_id)
    if not parent_asset:
        return jsonify({"ok": False, "error": "Parent asset not found in SnipeOps Catalog."}), 404

    child_assets = get_assets_assigned_to_asset(asset_id)

    return jsonify({
        "ok": True,
        "parent_asset": _asset_payload(parent_asset),
        "count": len(child_assets),
        "assets": [_asset_payload(row) for row in child_assets],
    })