from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, session

from modules.core.auth.decorators import login_required, require_permission
from modules.core.identity.user_service import get_user_by_id
from modules.core.identity.identity_db import get_connection

from apps.snipeops.snipe_catalog.catalog_db import (
    get_asset,
    search_assets,
    get_assets_assigned_to_asset,
    list_cart_assets,
)
from apps.snipeops.snipe_catalog.sync import run_full_sync
from apps.snipeops.checkout_assets.snipe import build_asset_url

from apps.snipeops.media_catalog.media_catalog_db import (
    get_recent,
    log_media_action,
    list_owned_carts,
    get_cart_ownership,
    claim_cart,
    update_cart_metadata,
    reorder_owned_cart,
)

from apps.snipeops.media_catalog.snipe import (
    checkin_asset,
    checkout_asset_to_cart,
)


bp = Blueprint(
    "media_catalog",
    __name__,
    url_prefix="/snipeops/media-catalog",
    template_folder="templates",
    static_folder="static",
)


def _body() -> dict:
    return request.get_json(silent=True) or request.form.to_dict(flat=True)

def _search_users(query: str, limit: int = 25) -> list[dict]:
    query = (query or "").strip()

    if len(query) < 2:
        return []

    like = f"%{query.lower()}%"

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM users
            WHERE is_active = 1
              AND (
                lower(coalesce(email, '')) LIKE ?
                OR lower(coalesce(username, '')) LIKE ?
                OR lower(coalesce(display_name, '')) LIKE ?
                OR lower(coalesce(first_name, '')) LIKE ?
                OR lower(coalesce(last_name, '')) LIKE ?
                OR lower(coalesce(department, '')) LIKE ?
                OR lower(coalesce(office_location, '')) LIKE ?
              )
            ORDER BY display_name, email
            LIMIT ?
            """,
            (like, like, like, like, like, like, like, int(limit)),
        ).fetchall()

    return [dict(row) for row in rows]

def _current_user_profile() -> dict | None:
    user_id = session.get("user_id")
    if not user_id:
        return None

    try:
        return get_user_by_id(int(user_id))
    except Exception:
        return None


def _asset_payload(asset: dict | None) -> dict | None:
    if not asset:
        return None

    ownership = get_cart_ownership(int(asset["id"])) if asset.get("id") else None

    return {
        "id": asset.get("id"),
        "asset_tag": asset.get("asset_tag") or "",
        "serial": asset.get("serial") or "",
        "name": asset.get("name") or "",
        "model_name": asset.get("model_name") or "",
        "category_name": asset.get("category_name") or "",
        "status_name": asset.get("status_name") or "",
        "location_name": asset.get("location_name") or "",
        "assigned_type": asset.get("assigned_type") or "",
        "assigned_id": asset.get("assigned_id"),
        "assigned_name": asset.get("assigned_name") or "",
        "asset_url": build_asset_url(asset.get("id")),
        "ownership": ownership,
    }


def _ownership_payload(row: dict) -> dict:
    cart = get_asset(int(row["cart_asset_id"]))

    payload = _asset_payload(cart) if cart else {
        "id": row.get("cart_asset_id"),
        "asset_tag": row.get("cart_asset_tag") or "",
        "name": row.get("cart_name") or "",
        "model_name": "",
        "category_name": "",
        "status_name": "",
        "location_name": "",
        "assigned_type": "",
        "assigned_id": None,
        "assigned_name": "",
        "asset_url": build_asset_url(row.get("cart_asset_id")),
        "ownership": row,
    }

    payload["ownership"] = row
    return payload


@bp.get("/")
@login_required
@require_permission("snipeops.media_catalog.view")
def index():
    return render_template("media_catalog/index.html", recent=get_recent(50))


@bp.get("/api/me")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_me():
    user = _current_user_profile()

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    return jsonify({
        "ok": True,
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "display_name": user.get("display_name") or user.get("email"),
            "office_location": user.get("office_location") or "",
            "department": user.get("department") or "",
        },
    })


@bp.get("/api/my-carts")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_my_carts():
    user = _current_user_profile()

    if not user:
        return jsonify({"ok": False, "error": "User profile not found.", "carts": []}), 404

    rows = list_owned_carts(int(user["id"]))

    return jsonify({
        "ok": True,
        "carts": [_ownership_payload(row) for row in rows],
    })


@bp.get("/api/carts")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_carts():
    query = (request.args.get("q") or "").strip()

    if query:
        carts = [
            row for row in search_assets(query, limit=100)
            if "cart" in f"{row.get('name', '')} {row.get('asset_tag', '')} {row.get('category_name', '')}".lower()
        ]
    else:
        carts = list_cart_assets(limit=250)

    return jsonify({
        "ok": True,
        "carts": [_asset_payload(cart) for cart in carts],
    })


@bp.get("/api/carts/<int:cart_id>/devices")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_cart_devices(cart_id: int):
    cart = get_asset(cart_id)

    if not cart:
        return jsonify({"ok": False, "error": "Cart not found."}), 404

    devices = get_assets_assigned_to_asset(cart_id)

    return jsonify({
        "ok": True,
        "cart": _asset_payload(cart),
        "devices": [_asset_payload(device) for device in devices],
    })


@bp.post("/api/carts/<int:cart_id>/claim")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_claim_cart(cart_id: int):
    user = _current_user_profile()
    cart = get_asset(cart_id)

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    if not cart:
        return jsonify({"ok": False, "error": "Cart not found."}), 404

    previous_ownership = get_cart_ownership(cart_id)
    ownership = claim_cart(cart_asset=cart, user=user)

    previous_owner = ""
    if previous_ownership:
        previous_owner = (
            previous_ownership.get("owner_display_name")
            or previous_ownership.get("owner_email")
            or ""
        )

    new_owner = user.get("display_name") or user.get("email") or ""

    if previous_owner and previous_owner != new_owner:
        message = f"Cart ownership moved from {previous_owner} to {new_owner}."
    else:
        message = f"Cart ownership claimed by {new_owner}."

    log_media_action(
        action="claimed_cart",
        cart_asset=cart,
        device_asset=None,
        ok=True,
        message=message,
        actor_user=user,
    )

    return jsonify({
        "ok": True,
        "message": message,
        "cart": _asset_payload(cart),
        "ownership": ownership,
    })


@bp.post("/api/add-to-cart")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_add_to_cart():
    body = _body()

    try:
        cart_id = int(body.get("cart_id") or 0)
        device_id = int(body.get("device_id") or 0)
        force = bool(body.get("force"))
    except Exception:
        return jsonify({"ok": False, "error": "Invalid cart or device id."}), 400

    cart = get_asset(cart_id)
    device = get_asset(device_id)
    actor_user = _current_user_profile()

    if not cart or not device:
        return jsonify({"ok": False, "error": "Cart or device not found."}), 404

    current_assigned_name = device.get("assigned_name") or ""
    current_assigned_id = int(device.get("assigned_id") or 0)

    if current_assigned_name and current_assigned_id != int(cart["id"]) and not force:
        return jsonify({
            "ok": False,
            "needs_confirmation": True,
            "message": (
                f'This device is currently assigned to "{current_assigned_name}". '
                f'Do you want to move it to "{cart.get("name") or cart.get("asset_tag")}"?'
            ),
            "device": _asset_payload(device),
            "cart": _asset_payload(cart),
        }), 409

    try:
        if force and current_assigned_id and current_assigned_id != int(cart["id"]):
            checkin_asset(
                asset_id=int(device["id"]),
                note="Checked in before move by SnipeOps Media Catalog.",
            )

        checkout_asset_to_cart(
            child_asset_id=int(device["id"]),
            cart_asset_id=int(cart["id"]),
            note="Moved to cart by SnipeOps Media Catalog." if force else "Added to cart by SnipeOps Media Catalog.",
        )

        action = "moved_to_cart" if force else "added_to_cart"
        message = "Device moved to cart." if force else "Device assigned to cart."

        log_media_action(
            action=action,
            cart_asset=cart,
            device_asset=device,
            ok=True,
            message=message,
            actor_user=actor_user,
        )

        return jsonify({
            "ok": True,
            "message": message,
            "cart": _asset_payload(cart),
            "device": _asset_payload(device),
        })

    except Exception as exc:
        log_media_action(
            action="move_failed" if force else "add_failed",
            cart_asset=cart,
            device_asset=device,
            ok=False,
            message=str(exc),
            actor_user=actor_user,
        )

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@bp.post("/api/remove-from-cart")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_remove_from_cart():
    body = _body()
    device_id = int(body.get("device_id") or 0)
    actor_user = _current_user_profile()

    device = get_asset(device_id)

    if not device:
        return jsonify({"ok": False, "error": "Device not found."}), 404
    
    cart_asset = None
    assigned_id = device.get("assigned_id")

    if assigned_id:
        try:
            cart_asset = get_asset(int(assigned_id))
        except Exception:
            cart_asset = None

    checkin_asset(
        asset_id=int(device["id"]),
        note="Removed from cart by SnipeOps Media Catalog.",
    )

    log_media_action(
        action="removed_from_cart",
        cart_asset=cart_asset,
        device_asset=device,
        ok=True,
        message="Device removed from cart and checked in.",
        actor_user=actor_user,
    )

    return jsonify({
        "ok": True,
        "message": "Device removed from cart and checked in.",
        "device": _asset_payload(device),
    })


@bp.post("/api/sync-snipe")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_sync_snipe():
    result = run_full_sync()
    return jsonify(result), (200 if result.get("ok") else 500)


@bp.get("/api/search")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_search():
    query = (request.args.get("q") or "").strip()
    rows = search_assets(query, limit=100)

    return jsonify({
        "ok": True,
        "results": [_asset_payload(row) for row in rows],
    })

@bp.get("/api/users/search")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def api_user_search():
    query = (request.args.get("q") or "").strip()

    if len(query) < 2:
        return jsonify({"ok": True, "users": []})

    users = _search_users(query, limit=25)

    return jsonify({
        "ok": True,
        "users": [
            {
                "id": user.get("id"),
                "email": user.get("email") or "",
                "display_name": user.get("display_name") or user.get("email") or "",
                "department": user.get("department") or "",
                "office_location": user.get("office_location") or "",
                "is_active": user.get("is_active", 0),
            }
            for user in users
            if user.get("is_active", 0)
        ],
    })

@bp.post("/api/carts/<int:cart_id>/assign-owner")
@login_required
@require_permission("snipeops.media_catalog.ownership.manage")
def api_assign_cart_owner(cart_id: int):
    body = _body()

    try:
        owner_user_id = int(body.get("owner_user_id") or 0)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid owner user id."}), 400

    actor_user = _current_user_profile()
    cart = get_asset(cart_id)
    owner_user = get_user_by_id(owner_user_id)

    if not actor_user:
        return jsonify({"ok": False, "error": "Current user profile not found."}), 404

    if not cart:
        return jsonify({"ok": False, "error": "Cart not found."}), 404

    if not owner_user or not owner_user.get("is_active", 0):
        return jsonify({"ok": False, "error": "Selected user was not found or is inactive."}), 404

    previous_ownership = get_cart_ownership(cart_id)
    ownership = claim_cart(cart_asset=cart, user=owner_user)

    previous_owner = ""
    if previous_ownership:
        previous_owner = (
            previous_ownership.get("owner_display_name")
            or previous_ownership.get("owner_email")
            or ""
        )

    new_owner = owner_user.get("display_name") or owner_user.get("email") or ""

    if previous_owner and previous_owner != new_owner:
        message = f"Cart ownership assigned from {previous_owner} to {new_owner}."
    else:
        message = f"Cart ownership assigned to {new_owner}."

    log_media_action(
        action="assigned_cart_owner",
        cart_asset=cart,
        device_asset=None,
        ok=True,
        message=message,
        actor_user=actor_user,
    )

    return jsonify({
        "ok": True,
        "message": message,
        "cart": _asset_payload(cart),
        "ownership": ownership,
    })

@bp.post("/api/carts/<int:cart_id>/metadata")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_update_cart_metadata(cart_id: int):
    body = _body()
    user = _current_user_profile()
    cart = get_asset(cart_id)

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    if not cart:
        return jsonify({"ok": False, "error": "Cart not found."}), 404

    ownership = get_cart_ownership(cart_id)

    if not ownership:
        return jsonify({"ok": False, "error": "Cart ownership record not found."}), 404

    if int(ownership.get("owner_user_id") or 0) != int(user["id"]):
        return jsonify({"ok": False, "error": "You can only edit carts assigned to you."}), 403

    updated = update_cart_metadata(
        cart_asset_id=cart_id,
        owner_user_id=int(user["id"]),
        media_specialist_owner=body.get("media_specialist_owner"),
        teacher_name=body.get("teacher_name"),
        room_number=body.get("room_number"),
    )

    log_media_action(
        action="updated_cart_metadata",
        cart_asset=cart,
        device_asset=None,
        ok=True,
        message="Cart friendly fields updated.",
        actor_user=user,
    )

    return jsonify({
        "ok": True,
        "message": "Cart friendly fields updated.",
        "cart": _ownership_payload(updated),
    })


@bp.post("/api/my-carts/reorder")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_reorder_my_carts():
    body = _body()
    user = _current_user_profile()

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    try:
        cart_id = int(body.get("cart_id") or 0)
        new_index = int(body.get("new_index") or 0)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid cart id or index."}), 400

    try:
        rows = reorder_owned_cart(
            owner_user_id=int(user["id"]),
            cart_asset_id=cart_id,
            new_index=new_index,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({
        "ok": True,
        "message": "Cart order updated.",
        "carts": [_ownership_payload(row) for row in rows],
    })