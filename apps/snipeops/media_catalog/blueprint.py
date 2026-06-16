from __future__ import annotations

from io import BytesIO
import re
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, session, send_file

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

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
from apps.snipeops.snipe_catalog.snipe_api import fetch_locations, patch_json

from apps.snipeops.checkout_assets.snipe import build_asset_url

from apps.snipeops.media_catalog.media_catalog_db import (
    get_recent,
    log_media_action,
    list_owned_carts,
    list_all_owned_carts,
    list_cart_owners,
    get_cart_ownership,
    claim_cart,
    update_cart_metadata,
    update_cart_metadata_admin,
    reorder_owned_cart,
)

from apps.snipeops.media_catalog.snipe import (
    checkin_asset,
    checkout_asset_to_cart,
)

from modules.core.settings.settings_service import get_setting

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

def _safe_filename(value: str) -> str:
    value = (value or "media-catalog-export").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = value.strip("-")
    return value or "media-catalog-export"

def _export_date_stamp() -> str:
    return datetime.now().strftime("%m-%d-%y")


def _can_manage_ownership() -> bool:
    return "snipeops.media_catalog.ownership.manage" in session.get("user_permissions", [])


def _cart_export_payload(cart_id: int) -> dict | None:
    cart = get_asset(int(cart_id))
    if not cart:
        return None

    ownership = get_cart_ownership(int(cart_id)) or {}
    devices = get_assets_assigned_to_asset(int(cart_id))

    return {
        "cart": _asset_payload(cart),
        "ownership": ownership,
        "devices": [_asset_payload(device) for device in devices],
    }


def _build_carts_pdf(title: str, cart_payloads: list[dict]) -> BytesIO:
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=0.35 * inch,
        leftMargin=0.35 * inch,
        topMargin=0.35 * inch,
        bottomMargin=0.35 * inch,
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 0.15 * inch))

    if not cart_payloads:
        story.append(Paragraph("No carts found for this export.", styles["Normal"]))
    else:
        for index, payload in enumerate(cart_payloads):
            cart = payload["cart"] or {}
            ownership = payload["ownership"] or {}
            devices = payload["devices"] or []

            if index > 0:
                story.append(PageBreak())

            cart_label = cart.get("asset_tag") or cart.get("name") or f"Cart {cart.get('id')}"
            story.append(Paragraph(f"Cart {cart_label}", styles["Heading1"]))

            details = [
                ["Cart Name", cart.get("name") or "—"],
                ["Teacher", ownership.get("teacher_name") or "—"],
                ["Room", ownership.get("room_number") or "—"],
                ["Location", cart.get("location_name") or "—"],
                ["Model", cart.get("model_name") or "—"],
                ["Device Count", str(len(devices))],
            ]

            details_table = Table(details, colWidths=[1.3 * inch, 5.6 * inch])
            details_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(details_table)
            story.append(Spacer(1, 0.18 * inch))

            device_rows = [["#", "Asset Tag", "Serial", "Model", "Status", "Location"]]
            for device_index, device in enumerate(devices, start=1):
                device_rows.append([
                    str(device_index),
                    device.get("asset_tag") or "",
                    device.get("serial") or "",
                    device.get("model_name") or "",
                    device.get("status_name") or "",
                    device.get("location_name") or "",
                ])

            if len(device_rows) == 1:
                device_rows.append(["", "No devices assigned to this cart.", "", "", "", ""])

            device_table = Table(
                device_rows,
                colWidths=[
                    0.35 * inch,  # #
                    0.75 * inch,  # Asset Tag
                    1.75 * inch,  # Serial
                    2.2 * inch,   # Model
                    1.1 * inch,   # Status
                    1.6 * inch,   # Location
                ],
                repeatRows=1,
            )
            device_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("PADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(device_table)

    doc.build(story)
    buffer.seek(0)
    return buffer


def _send_pdf(buffer: BytesIO, filename: str):
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@bp.get("/")
@login_required
@require_permission("snipeops.media_catalog.view")
def index():
    system_timezone = get_setting("general.timezone", "America/Chicago") or "America/Chicago"

    return render_template(
        "media_catalog/index.html",
        recent=get_recent(50),
        system_timezone=system_timezone,
    )


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

@bp.get("/api/ownership/owners")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def api_ownership_owners():
    owners = list_cart_owners()

    return jsonify({
        "ok": True,
        "owners": owners,
    })


@bp.get("/api/ownership/users/<int:user_id>/carts")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def api_ownership_user_carts(user_id: int):
    rows = list_owned_carts(user_id)

    return jsonify({
        "ok": True,
        "carts": [_ownership_payload(row) for row in rows],
    })


@bp.get("/api/ownership/carts")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def api_ownership_all_carts():
    rows = list_all_owned_carts()

    return jsonify({
        "ok": True,
        "carts": [_ownership_payload(row) for row in rows],
    })


@bp.post("/api/admin/carts/<int:cart_id>/metadata")
@login_required
@require_permission("snipeops.media_catalog.ownership.manage")
def api_admin_update_cart_metadata(cart_id: int):
    body = _body()
    actor_user = _current_user_profile()
    cart = get_asset(cart_id)

    if not actor_user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    if not cart:
        return jsonify({"ok": False, "error": "Cart not found."}), 404

    ownership = get_cart_ownership(cart_id)
    if not ownership:
        return jsonify({"ok": False, "error": "Cart ownership record not found."}), 404

    updated = update_cart_metadata_admin(
        cart_asset_id=cart_id,
        media_specialist_owner=body.get("media_specialist_owner"),
        teacher_name=body.get("teacher_name"),
        room_number=body.get("room_number"),
    )

    log_media_action(
        action="admin_updated_cart_metadata",
        cart_asset=cart,
        device_asset=None,
        ok=True,
        message="Cart friendly fields updated by admin.",
        actor_user=actor_user,
    )

    return jsonify({
        "ok": True,
        "message": "Cart friendly fields updated.",
        "cart": _ownership_payload(updated),
    })


@bp.get("/export/cart/<int:cart_id>.pdf")
@login_required
@require_permission("snipeops.media_catalog.view")
def export_cart_pdf(cart_id: int):
    payload = _cart_export_payload(cart_id)

    if not payload:
        return jsonify({"ok": False, "error": "Cart not found."}), 404

    ownership = payload.get("ownership") or {}
    user = _current_user_profile()

    if not _can_manage_ownership():
        if not user or int(ownership.get("owner_user_id") or 0) != int(user["id"]):
            return jsonify({"ok": False, "error": "You can only export carts assigned to you."}), 403

    cart = payload["cart"] or {}
    filename = _safe_filename(
        f"cart-{cart.get('asset_tag') or cart_id}-{_export_date_stamp()}.pdf"
    )

    pdf = _build_carts_pdf(
        title=f"Media Catalog Export - Cart {cart.get('asset_tag') or cart_id}",
        cart_payloads=[payload],
    )

    return _send_pdf(pdf, filename)


@bp.get("/export/my-carts.pdf")
@login_required
@require_permission("snipeops.media_catalog.view")
def export_my_carts_pdf():
    user = _current_user_profile()

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    rows = list_owned_carts(int(user["id"]))
    payloads = [
        payload
        for row in rows
        if (payload := _cart_export_payload(int(row["cart_asset_id"])))
    ]

    pdf = _build_carts_pdf(
        title=f"Media Catalog Export - {user.get('display_name') or user.get('email') or 'My Carts'}",
        cart_payloads=payloads,
    )

    return _send_pdf(pdf, f"my-media-carts-{_export_date_stamp()}.pdf")


@bp.get("/export/user/<int:user_id>/carts.pdf")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def export_user_carts_pdf(user_id: int):
    owner = get_user_by_id(user_id)

    if not owner:
        return jsonify({"ok": False, "error": "User not found."}), 404

    rows = list_owned_carts(user_id)
    payloads = [
        payload
        for row in rows
        if (payload := _cart_export_payload(int(row["cart_asset_id"])))
    ]

    owner_label = owner.get("display_name") or owner.get("email") or f"user-{user_id}"

    pdf = _build_carts_pdf(
        title=f"Media Catalog Export - {owner_label}",
        cart_payloads=payloads,
    )

    return _send_pdf(
        pdf,
        _safe_filename(f"media-carts-{owner_label}-{_export_date_stamp()}.pdf"),
    )


@bp.get("/export/all-assigned-carts.pdf")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def export_all_assigned_carts_pdf():
    rows = list_all_owned_carts()
    payloads = [
        payload
        for row in rows
        if (payload := _cart_export_payload(int(row["cart_asset_id"])))
    ]

    pdf = _build_carts_pdf(
        title="Media Catalog Export - All Assigned Carts",
        cart_payloads=payloads,
    )

    return _send_pdf(
        pdf,
        f"all-assigned-media-carts-{_export_date_stamp()}.pdf",
    )


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

@bp.get("/api/locations")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_locations():
    query = (request.args.get("q") or "").strip().lower()

    rows = fetch_locations()

    locations = []
    for row in rows:
        name = row.get("name") or ""
        if query and query not in name.lower():
            continue

        locations.append({
            "id": row.get("id"),
            "name": name,
        })

    locations.sort(key=lambda item: item["name"].lower())

    return jsonify({
        "ok": True,
        "locations": locations,
    })


@bp.post("/api/carts/<int:cart_id>/location")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_update_cart_location(cart_id: int):
    body = _body()
    user = _current_user_profile()
    cart = get_asset(cart_id)

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    if not cart:
        return jsonify({"ok": False, "error": "Cart not found."}), 404

    ownership = get_cart_ownership(cart_id)

    if not _can_manage_ownership():
        if not ownership or int(ownership.get("owner_user_id") or 0) != int(user["id"]):
            return jsonify({"ok": False, "error": "You can only update locations for carts assigned to you."}), 403

    try:
        location_id = int(body.get("location_id") or 0)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid location id."}), 400

    if location_id <= 0:
        return jsonify({"ok": False, "error": "Location is required."}), 400

    patch_json(
        f"/api/v1/hardware/{int(cart_id)}",
        {
            "rtd_location_id": location_id,
        },
    )

    log_media_action(
        action="updated_cart_location",
        cart_asset=cart,
        device_asset=None,
        ok=True,
        message="Cart location updated in Snipe-IT.",
        actor_user=user,
    )

    return jsonify({
        "ok": True,
        "message": "Cart location updated in Snipe-IT. Run Sync Snipe-IT if the new location does not show immediately.",
    })