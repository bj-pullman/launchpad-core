from __future__ import annotations

from io import BytesIO, StringIO
import csv
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

from tasks.job_runs import get_recent_job_runs

from modules.core.auth.decorators import login_required, require_permission
from modules.core.identity.user_service import get_user_by_id
from modules.core.identity.identity_db import get_connection

from apps.snipeops.snipe_catalog.catalog_db import (
    get_asset,
    search_assets,
    search_asset_catalog,
    search_cart_assets,
    get_assets_assigned_to_asset,
    count_assets_assigned_to_assets,
    list_cart_assets,
    update_asset_assignment,
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
    unassign_cart,
    update_cart_metadata,
    update_cart_metadata_admin,
    reorder_owned_cart,
)

from apps.snipeops.media_catalog.student_checkout_service import (
    STUDENT_CHECKOUT_PERMISSION,
    StudentCheckoutDuplicateError,
    StudentCheckoutError,
    attach_checkout_summaries_to_carts,
    checkout_lookup_payload,
    create_student_checkout,
    list_student_checkouts_for_scope,
    recent_student_checkout_activity,
    return_student_checkout,
    scoped_cart_ids_for_user,
    scoped_cart_rows_for_user,
    scoped_student_checkout_summary,
    user_can_access_cart,
)

from apps.snipeops.media_catalog.snipe import (
    checkin_asset,
    checkout_asset_to_cart,
    sync_cart_metadata_to_snipe,
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

def _ownership_rows_with_device_counts(rows: list[dict]) -> list[dict]:
    """
    Convert ownership rows to cart payloads and attach device counts
    using one aggregate catalog query.
    """
    cart_ids = [
        int(row["cart_asset_id"])
        for row in rows
        if row.get("cart_asset_id") is not None
    ]

    device_counts = count_assets_assigned_to_assets(cart_ids)

    payloads = []

    for row in rows:
        payload = _ownership_payload(row)

        cart_id = payload.get("id")
        payload["device_count"] = (
            device_counts.get(int(cart_id), 0)
            if cart_id is not None
            else 0
        )

        payloads.append(payload)

    return attach_checkout_summaries_to_carts(payloads)

def _safe_filename(value: str) -> str:
    value = (value or "media-catalog-export").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = value.strip("-")
    return value or "media-catalog-export"

def _export_date_stamp() -> str:
    return datetime.now().strftime("%m-%d-%y")


def _can_manage_ownership() -> bool:
    return "snipeops.media_catalog.ownership.manage" in session.get("user_permissions", [])

def _can_view_ownership() -> bool:
    return (
        "snipeops.media_catalog.ownership.view"
        in session.get("user_permissions", [])
    )

def _can_manage_student_checkouts() -> bool:
    return STUDENT_CHECKOUT_PERMISSION in session.get("user_permissions", [])


def _can_manage_media_catalog() -> bool:
    return "snipeops.media_catalog.manage" in session.get("user_permissions", [])


def _can_manage_all_carts() -> bool:
    permissions = session.get("user_permissions", [])
    return (
        "snipeops.media_catalog.ownership.manage" in permissions
        or "snipeops.home.manage" in permissions
    )


def _is_cart_asset(asset: dict | None) -> bool:
    if not asset:
        return False
    category = str(asset.get("category_name") or "").lower()
    model = str(asset.get("model_name") or "").lower()
    tag = str(asset.get("asset_tag") or "").lower()
    name = str(asset.get("name") or "").strip().lower()
    return (
        "cart" in category
        or "cart" in model
        or "cart" in tag
        or name.startswith("cart ")
        or name == "cart"
    )


def _asset_unavailable_reason(asset: dict | None) -> str | None:
    if not asset:
        return "Asset does not exist."
    status = str(asset.get("status_name") or "").strip().lower()
    blocked = ("archived", "deleted", "retired", "disposed", "lost", "stolen")
    if any(value in status for value in blocked):
        return f'Asset status "{asset.get("status_name")}" is not eligible for cart assignment.'
    return None


def _asset_status_tone(status_name: str | None) -> str:
    """Map free-form Snipe-IT status labels to shared semantic badge tones."""
    status = re.sub(r"\s+", " ", str(status_name or "").strip().lower())

    if any(label in status for label in ("lost", "stolen")):
        return "danger"
    if any(label in status for label in ("retired", "archived", "disposed")):
        return "muted"
    if any(label in status for label in ("in repair", "pending", "needs attention", "undeployable")):
        return "warning"
    if status == "deployable" or "ready to deploy" in status:
        return "success"
    if "deployed" in status or "assigned" in status or status == "active":
        return "info"
    return "neutral"


def _can_target_cart(user: dict | None, cart_id: int) -> bool:
    if not user:
        return False
    if _can_manage_all_carts():
        return True
    ownership = get_cart_ownership(int(cart_id))
    try:
        return bool(ownership and int(ownership.get("owner_user_id")) == int(user["id"]))
    except (TypeError, ValueError, KeyError):
        return False


def _catalog_asset_payload(asset: dict) -> dict:
    payload = _asset_payload(asset) or {}
    payload["status_tone"] = _asset_status_tone(asset.get("status_name"))
    current_cart = None
    if str(asset.get("assigned_type") or "").lower() == "asset" and asset.get("assigned_id"):
        parent = get_asset(int(asset["assigned_id"]))
        if parent and _is_cart_asset(parent):
            current_cart = _asset_payload(parent)
        elif asset.get("current_cart_asset_tag") or asset.get("current_cart_name"):
            current_cart = {
                "id": asset.get("assigned_id"),
                "asset_tag": asset.get("current_cart_asset_tag") or "",
                "name": asset.get("current_cart_name") or asset.get("assigned_name") or "",
                "location_name": asset.get("current_cart_location") or "",
            }
    payload["current_cart"] = current_cart
    payload["is_cart"] = _is_cart_asset(asset)
    payload["unavailable_reason"] = _asset_unavailable_reason(asset)
    payload["can_add_to_cart"] = bool(
        _can_manage_media_catalog()
        and not payload["is_cart"]
        and not payload["unavailable_reason"]
    )
    return payload


def _cart_search_text(cart: dict) -> str:
    ownership = cart.get("ownership") or {}
    return " ".join(str(value or "") for value in (
        cart.get("asset_tag"), cart.get("name"), cart.get("location_name"),
        ownership.get("owner_display_name"), ownership.get("owner_email"),
        ownership.get("media_specialist_owner"), ownership.get("teacher_name"),
        ownership.get("room_number"),
    )).lower()


def _student_checkout_error_response(exc: StudentCheckoutError):
    payload = {
        "ok": False,
        "error": exc.message,
    }

    if isinstance(exc, StudentCheckoutDuplicateError):
        payload["existing_checkout"] = exc.existing_checkout

    return jsonify(payload), exc.status_code


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

def _send_csv(csv_text: str, filename: str):
    buffer = BytesIO(csv_text.encode("utf-8-sig"))
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


def _sync_cart_metadata_fields(cart: dict, ownership: dict) -> tuple[dict | None, str | None]:
    try:
        devices = get_assets_assigned_to_asset(int(cart["id"]))
        result = sync_cart_metadata_to_snipe(
            cart_asset=cart,
            device_assets=devices,
            teacher_name=ownership.get("teacher_name") or "",
            room_number=ownership.get("room_number") or "",
        )
        return result, None
    except Exception as exc:
        return None, str(exc)


def _metadata_message(base_message: str, sync_result: dict | None, sync_error: str | None) -> str:
    if sync_error:
        return f"{base_message} Snipe-IT sync warning: {sync_error}"

    if not sync_result:
        return base_message

    message = (
        f"{base_message} Synced custom fields to "
        f"{int(sync_result.get('updated_assets') or 0)} Snipe-IT asset(s)."
    )

    skipped_model_ids = sync_result.get("skipped_model_ids") or []
    if skipped_model_ids:
        message += (
            " Some models already have a different custom fieldset and were not changed: "
            + ", ".join(str(item) for item in skipped_model_ids)
            + "."
        )

    return message


def _build_carts_csv(cart_payloads: list[dict], *, include_devices: bool) -> str:
    output = StringIO()

    if include_devices:
        fieldnames = [
            "assigned_to_cart_asset_tag",
            "device_asset_tag",
            "device_serial",
            "device_name",
            "device_model",
            "device_status",
            "device_location",
            "device_snipe_url",
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for payload in cart_payloads:
            cart = payload.get("cart") or {}
            devices = payload.get("devices") or []
            cart_asset_tag = cart.get("asset_tag") or ""

            for device in devices:
                writer.writerow({
                    "assigned_to_cart_asset_tag": cart_asset_tag,
                    "device_asset_tag": device.get("asset_tag") or "",
                    "device_serial": device.get("serial") or "",
                    "device_name": device.get("name") or "",
                    "device_model": device.get("model_name") or "",
                    "device_status": device.get("status_name") or "",
                    "device_location": device.get("location_name") or "",
                    "device_snipe_url": device.get("asset_url") or "",
                })

        return output.getvalue()

    fieldnames = [
        "owner_name",
        "owner_email",
        "cart_asset_tag",
        "cart_name",
        "cart_model",
        "cart_status",
        "cart_location",
        "teacher_name",
        "room_number",
        "device_count",
        "cart_snipe_url",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for payload in cart_payloads:
        cart = payload.get("cart") or {}
        ownership = payload.get("ownership") or {}
        devices = payload.get("devices") or []

        writer.writerow({
            "owner_name": ownership.get("owner_display_name") or "",
            "owner_email": ownership.get("owner_email") or "",
            "cart_asset_tag": cart.get("asset_tag") or "",
            "cart_name": cart.get("name") or "",
            "cart_model": cart.get("model_name") or "",
            "cart_status": cart.get("status_name") or "",
            "cart_location": cart.get("location_name") or "",
            "teacher_name": ownership.get("teacher_name") or "",
            "room_number": ownership.get("room_number") or "",
            "device_count": len(devices),
            "cart_snipe_url": cart.get("asset_url") or "",
        })

    return output.getvalue()

def _catalog_sync_runs(limit: int = 15) -> list[dict]:
    runs = get_recent_job_runs(
        job_id="snipe.catalog_sync",
        limit=limit,
    )

    payload = []

    for run in runs:
        status = str(run.get("status") or "").strip().lower()

        started_at = run.get("started_at")
        finished_at = run.get("finished_at")

        duration_seconds = None

        if started_at and finished_at:
            try:
                started = datetime.fromisoformat(
                    str(started_at).replace("Z", "+00:00")
                )
                finished = datetime.fromisoformat(
                    str(finished_at).replace("Z", "+00:00")
                )

                duration_seconds = max(
                    0,
                    round(
                        (finished - started).total_seconds(),
                        1,
                    ),
                )
            except (TypeError, ValueError):
                duration_seconds = None

        payload.append({
            **run,
            "status": status or "unknown",
            "duration_seconds": duration_seconds,
        })

    return payload


@bp.get("/")
@login_required
@require_permission("snipeops.media_catalog.view")
def index():
    system_timezone = (
        get_setting(
            "general.timezone",
            "America/Chicago",
        )
        or "America/Chicago"
    )

    return render_template(
        "media_catalog/index.html",
        recent=get_recent(50),
        catalog_sync_runs=_catalog_sync_runs(15),
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


@bp.get("/api/dashboard")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_dashboard():
    user = _current_user_profile()

    if not user:
        return jsonify({
            "ok": False,
            "error": "User profile not found.",
        }), 404

    # ---------------------------------------------------------
    # Determine dashboard scope.
    #
    # Anyone with Ownership Management VIEW access gets the
    # management-wide dashboard.
    #
    # Everyone else gets only carts assigned to them.
    # ---------------------------------------------------------
    management_scope = _can_view_ownership()

    if management_scope:
        scope_rows = list_all_owned_carts()
    else:
        scope_rows = list_owned_carts(
            int(user["id"])
        )

    cart_ids = [
        int(row["cart_asset_id"])
        for row in scope_rows
        if row.get("cart_asset_id") is not None
    ]

    # ---------------------------------------------------------
    # Device totals
    #
    # Use the aggregate catalog helper so we do not load every
    # device record into memory just to calculate the dashboard.
    # ---------------------------------------------------------
    device_counts = (
        count_assets_assigned_to_assets(cart_ids)
        if cart_ids
        else {}
    )

    total_devices = sum(
        int(device_counts.get(cart_id, 0))
        for cart_id in cart_ids
    )

    # ---------------------------------------------------------
    # Student Checkout totals
    #
    # This uses THE SAME cart scope as the device/cart totals.
    #
    # Ownership Management viewer:
    #     all assigned Media Catalog carts
    #
    # Normal Media Specialist:
    #     only their assigned carts
    # ---------------------------------------------------------
    if cart_ids:
        checkout_summary = (
            scoped_student_checkout_summary(
                cart_ids
            )
        )
    else:
        checkout_summary = {
            "active_count": 0,
            "overdue_count": 0,
        }

    # ---------------------------------------------------------
    # Needs Attention
    #
    # Show actual overdue checkout records rather than hydrating
    # cart objects just to create warnings.
    #
    # IMPORTANT:
    # This uses the SAME district/personal scope determined above.
    # ---------------------------------------------------------
    overdue_checkouts = (
        list_student_checkouts_for_scope(
            cart_asset_ids=cart_ids,
            status_filter="overdue",
            query="",
            limit=8,
        )
        if cart_ids
        else []
    )

    # ---------------------------------------------------------
    # Recent Activity
    #
    # This must also use THE SAME dashboard scope.
    #
    # An Ownership Management viewer therefore sees recent
    # Student Checkout activity across all assigned carts.
    # ---------------------------------------------------------
    recent_checkouts = (
        recent_student_checkout_activity(
            cart_asset_ids=cart_ids,
            limit=8,
        )
        if cart_ids
        else []
    )

    return jsonify({
        "ok": True,

        # Frontend uses this to change dashboard wording.
        "scope_mode": (
            "management"
            if management_scope
            else "personal"
        ),

        "summary": {
            "cart_count": len(cart_ids),

            "device_count":
                total_devices,

            "active_checkout_count":
                checkout_summary["active_count"],

            "overdue_checkout_count":
                checkout_summary["overdue_count"],
        },

        # -----------------------------------------------------
        # Needs Attention
        # -----------------------------------------------------
        "attention": {
            "overdue_checkouts":
                overdue_checkouts,
        },

        # -----------------------------------------------------
        # Recent Activity
        # -----------------------------------------------------
        "recent_student_checkouts":
            recent_checkouts,

        # -----------------------------------------------------
        # Permission / scope metadata
        # -----------------------------------------------------
        "can_manage_student_checkouts":
            _can_manage_student_checkouts(),

        "can_view_ownership":
            management_scope,

        "can_manage_ownership":
            _can_manage_ownership(),
    })


@bp.get("/api/my-carts")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_my_carts():
    user = _current_user_profile()

    if not user:
        return jsonify({
            "ok": False,
            "error": "User profile not found.",
            "carts": [],
            "total_devices_managed": 0,
        }), 404

    rows = list_owned_carts(int(user["id"]))
    carts = _ownership_rows_with_device_counts(rows)

    total_devices_managed = sum(
        int(cart.get("device_count") or 0)
        for cart in carts
    )

    return jsonify({
        "ok": True,
        "carts": carts,
        "total_devices_managed": total_devices_managed,
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

@bp.post("/api/carts/<int:cart_id>/unassign")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_unassign_cart(cart_id: int):
    actor_user = _current_user_profile()
    cart = get_asset(cart_id)
    ownership = get_cart_ownership(cart_id)

    if not actor_user:
        return jsonify({
            "ok": False,
            "error": "Current user profile not found.",
        }), 404

    if not cart:
        return jsonify({
            "ok": False,
            "error": "Cart not found.",
        }), 404

    if not ownership:
        return jsonify({
            "ok": False,
            "error": "This cart is not currently assigned to a Media Catalog owner.",
        }), 404

    can_manage_all_ownership = _can_manage_ownership()

    expected_owner_user_id = (
        None
        if can_manage_all_ownership
        else int(actor_user["id"])
    )

    try:
        previous_ownership = unassign_cart(
            cart_asset_id=cart_id,
            expected_owner_user_id=expected_owner_user_id,
        )
    except ValueError as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 403

    if not previous_ownership:
        return jsonify({
            "ok": False,
            "error": "Cart ownership record was not found.",
        }), 404

    previous_owner = (
        previous_ownership.get("owner_display_name")
        or previous_ownership.get("owner_email")
        or "the previous owner"
    )

    cart_label = (
        cart.get("asset_tag")
        or cart.get("name")
        or f"Cart {cart_id}"
    )

    message = (
        f'Cart "{cart_label}" was unassigned from {previous_owner}. '
        "Devices remain assigned to the cart."
    )

    log_media_action(
        action="unassigned_cart",
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
        "previous_ownership": previous_ownership,
    })


@bp.post("/api/add-to-cart")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_add_to_cart():
    body = _body()

    try:
        cart_id = int(body.get("cart_id") or 0)
        device_id = int(body.get("device_id") or 0)
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "Invalid cart or device id.",
        }), 400

    cart = get_asset(cart_id)
    device = get_asset(device_id)
    actor_user = _current_user_profile()

    if not actor_user:
        return jsonify({
            "ok": False,
            "error": "Current user profile not found.",
        }), 404

    if not cart:
        return jsonify({
            "ok": False,
            "error": "Target cart does not exist.",
        }), 404

    if not device:
        return jsonify({"ok": False, "error": "Asset does not exist."}), 404

    if not _is_cart_asset(cart):
        return jsonify({"ok": False, "error": "The selected target is not an eligible cart."}), 400

    if not _can_target_cart(actor_user, cart_id):
        return jsonify({
            "ok": False,
            "error": "You do not have permission to manage the selected cart.",
        }), 403

    cart_unavailable = _asset_unavailable_reason(cart)
    if cart_unavailable:
        return jsonify({"ok": False, "error": cart_unavailable}), 409

    device_unavailable = _asset_unavailable_reason(device)
    if device_unavailable:
        return jsonify({"ok": False, "error": device_unavailable}), 409

    if _is_cart_asset(device):
        return jsonify({"ok": False, "error": "Cart assets cannot be added inside another cart."}), 409

    if int(device["id"]) == int(cart["id"]):
        return jsonify({
            "ok": False,
            "error": "A cart cannot be assigned to itself.",
        }), 400

    current_assigned_id = None

    try:
        if device.get("assigned_id") is not None:
            current_assigned_id = int(device["assigned_id"])
    except (TypeError, ValueError):
        current_assigned_id = None

    current_assigned_name = device.get("assigned_name") or ""
    current_assigned_type = str(device.get("assigned_type") or "").strip().lower()
    destination_cart_id = int(cart["id"])

    already_in_destination = (
        current_assigned_id == destination_cart_id
        and current_assigned_type == "asset"
    )

    if already_in_destination:
        return jsonify({
            "ok": True,
            "message": "Device is already assigned to this cart.",
            "moved": False,
            "previous_cart_id": current_assigned_id,
            "cart": _asset_payload(cart),
            "device": _asset_payload(device),
        })

    if current_assigned_id is not None and current_assigned_type != "asset":
        return jsonify({
            "ok": False,
            "error": (
                f'Asset is currently assigned to {current_assigned_name or current_assigned_type}. '
                "Check it in through the appropriate Snipe-IT workflow before adding it to a cart."
            ),
            "assignment_type": current_assigned_type,
        }), 409

    moving_from_another_assignment = (
        current_assigned_id is not None
        and current_assigned_id != destination_cart_id
    )

    previous_cart = get_asset(current_assigned_id) if moving_from_another_assignment else None
    if moving_from_another_assignment and not _is_cart_asset(previous_cart):
        return jsonify({
            "ok": False,
            "error": "Asset is assigned to another asset that is not recognized as a Media Catalog cart.",
        }), 409

    confirmed_move = str(body.get("confirm_move") or body.get("force") or "").lower() in (
        "1", "true", "yes", "on"
    )
    if moving_from_another_assignment and not confirmed_move:
        return jsonify({
            "ok": False,
            "error": "This asset is currently assigned to another cart. Confirm the move to continue.",
            "confirmation_required": True,
            "source_cart": _asset_payload(previous_cart),
            "destination_cart": _asset_payload(cart),
            "device": _asset_payload(device),
        }), 409

    previous_cart_id = current_assigned_id
    previous_cart_name = current_assigned_name
    checked_in = False

    try:
        if moving_from_another_assignment:
            checkin_asset(
                asset_id=int(device["id"]),
                note=(
                    "Checked in before moving to another cart through "
                    "SnipeOps Media Catalog."
                ),
            )

            checked_in = True

            update_asset_assignment(
                int(device["id"]),
                assigned_type=None,
                assigned_id=None,
                assigned_name=None,
            )

        checkout_asset_to_cart(
            child_asset_id=int(device["id"]),
            cart_asset_id=destination_cart_id,
            note=(
                "Moved to cart by SnipeOps Media Catalog."
                if moving_from_another_assignment
                else "Added to cart by SnipeOps Media Catalog."
            ),
        )

        destination_name = (
            cart.get("name")
            or cart.get("asset_tag")
            or f"Cart {destination_cart_id}"
        )

        updated_device = update_asset_assignment(
            int(device["id"]),
            assigned_type="asset",
            assigned_id=destination_cart_id,
            assigned_name=destination_name,
        )

        if moving_from_another_assignment:
            if previous_cart_name:
                message = (
                    f'Device moved from "{previous_cart_name}" '
                    f'to "{destination_name}".'
                )
            else:
                message = f'Device moved to "{destination_name}".'

            action = "moved_to_cart"
        else:
            message = f'Device assigned to "{destination_name}".'
            action = "added_to_cart"

        log_media_action(
            action=action,
            cart_asset=cart,
            device_asset=updated_device or device,
            ok=True,
            message=message,
            actor_user=actor_user,
        )

        return jsonify({
            "ok": True,
            "message": message,
            "moved": moving_from_another_assignment,
            "previous_cart_id": previous_cart_id,
            "destination_cart_id": destination_cart_id,
            "cart": _asset_payload(cart),
            "device": _asset_payload(updated_device or device),
        })

    except Exception as exc:
        if checked_in:
            error_message = (
                "The device was removed from its previous assignment, but "
                f"could not be assigned to the destination cart. {exc}"
            )
        else:
            error_message = str(exc)

        latest_device = get_asset(int(device["id"]))

        log_media_action(
            action=(
                "move_failed"
                if moving_from_another_assignment
                else "add_failed"
            ),
            cart_asset=cart,
            device_asset=latest_device or device,
            ok=False,
            message=error_message,
            actor_user=actor_user,
        )

        return jsonify({
            "ok": False,
            "error": error_message,
            "partial_move": checked_in,
            "previous_cart_id": previous_cart_id,
            "destination_cart_id": destination_cart_id,
            "device": _asset_payload(latest_device or device),
        }), 500


@bp.post("/api/remove-from-cart")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_remove_from_cart():
    body = _body()

    try:
        device_id = int(body.get("device_id") or 0)
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "Invalid device id.",
        }), 400

    actor_user = _current_user_profile()
    device = get_asset(device_id)

    if not device:
        return jsonify({
            "ok": False,
            "error": "Device not found.",
        }), 404

    cart_asset = None
    previous_cart_id = None

    if device.get("assigned_id") is not None:
        try:
            previous_cart_id = int(device["assigned_id"])
            cart_asset = get_asset(previous_cart_id)
        except (TypeError, ValueError):
            previous_cart_id = None
            cart_asset = None

    try:
        checkin_asset(
            asset_id=int(device["id"]),
            note="Removed from cart by SnipeOps Media Catalog.",
        )

        updated_device = update_asset_assignment(
            int(device["id"]),
            assigned_type=None,
            assigned_id=None,
            assigned_name=None,
        )

        log_media_action(
            action="removed_from_cart",
            cart_asset=cart_asset,
            device_asset=updated_device or device,
            ok=True,
            message="Device removed from cart and checked in.",
            actor_user=actor_user,
        )

        return jsonify({
            "ok": True,
            "message": "Device removed from cart and checked in.",
            "previous_cart_id": previous_cart_id,
            "device": _asset_payload(updated_device or device),
        })

    except Exception as exc:
        log_media_action(
            action="remove_failed",
            cart_asset=cart_asset,
            device_asset=device,
            ok=False,
            message=str(exc),
            actor_user=actor_user,
        )

        return jsonify({
            "ok": False,
            "error": str(exc),
            "previous_cart_id": previous_cart_id,
        }), 500

@bp.post("/api/carts/<int:cart_id>/remove-all-devices")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_remove_all_devices(cart_id: int):
    actor_user = _current_user_profile()
    cart = get_asset(cart_id)

    if not actor_user:
        return jsonify({
            "ok": False,
            "error": "Current user profile not found.",
        }), 404

    if not cart:
        return jsonify({
            "ok": False,
            "error": "Cart not found.",
        }), 404

    devices = get_assets_assigned_to_asset(cart_id)

    if not devices:
        return jsonify({
            "ok": True,
            "message": "This cart does not have any assigned devices.",
            "cart": _asset_payload(cart),
            "removed_count": 0,
            "failed_count": 0,
            "failures": [],
        })

    removed_devices = []
    failures = []

    for device in devices:
        try:
            checkin_asset(
                asset_id=int(device["id"]),
                note=(
                    "Removed through the Remove All Devices action in "
                    "SnipeOps Media Catalog."
                ),
            )

            updated_device = update_asset_assignment(
                int(device["id"]),
                assigned_type=None,
                assigned_id=None,
                assigned_name=None,
            )

            removed_devices.append(
                _asset_payload(updated_device or device)
            )

        except Exception as exc:
            failures.append({
                "device_id": device.get("id"),
                "asset_tag": device.get("asset_tag") or "",
                "serial": device.get("serial") or "",
                "name": device.get("name") or "",
                "error": str(exc),
            })

    removed_count = len(removed_devices)
    failed_count = len(failures)
    total_count = len(devices)

    cart_label = (
        cart.get("asset_tag")
        or cart.get("name")
        or f"Cart {cart_id}"
    )

    if removed_count == total_count:
        action = "removed_all_devices"
        ok = True
        message = (
            f'Removed all {removed_count} device(s) from cart '
            f'"{cart_label}" and checked them into Snipe-IT.'
        )

    elif removed_count > 0:
        action = "remove_all_devices_partial"
        ok = False
        message = (
            f'Removed {removed_count} of {total_count} device(s) from '
            f'cart "{cart_label}". {failed_count} device(s) could not '
            "be removed."
        )

    else:
        action = "remove_all_devices_failed"
        ok = False
        message = (
            f'No devices could be removed from cart "{cart_label}". '
            f"All {failed_count} removal attempt(s) failed."
        )

    log_media_action(
        action=action,
        cart_asset=cart,
        device_asset=None,
        ok=ok,
        message=message,
        actor_user=actor_user,
    )

    return jsonify({
        # Keep this response HTTP 200 so the frontend can display
        # useful partial-success information.
        "ok": True,
        "complete_success": failed_count == 0,
        "partial_success": removed_count > 0 and failed_count > 0,
        "message": message,
        "cart": _asset_payload(cart),
        "removed_count": removed_count,
        "failed_count": failed_count,
        "removed_devices": removed_devices,
        "failures": failures,
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


@bp.get("/api/asset-catalog")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_asset_catalog():
    query = (request.args.get("q") or "").strip()
    try:
        page = max(1, int(request.args.get("page") or 1))
        per_page = min(100, max(10, int(request.args.get("per_page") or 25)))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid pagination values."}), 400

    result = search_asset_catalog(query, page=page, per_page=per_page)
    return jsonify({
        "ok": True,
        "query": query,
        "results": [_catalog_asset_payload(row) for row in result["results"]],
        "pagination": {
            "page": result["page"],
            "per_page": result["per_page"],
            "pages": result["pages"],
            "total": result["total"],
        },
        "can_add_to_cart": _can_manage_media_catalog(),
        "can_target_any_cart": _can_manage_all_carts(),
    })


@bp.get("/api/asset-catalog/carts")
@login_required
@require_permission("snipeops.media_catalog.manage")
def api_asset_catalog_carts():
    user = _current_user_profile()
    if not user:
        return jsonify({"ok": False, "error": "Current user profile not found."}), 404

    query = (request.args.get("q") or "").strip().lower()
    can_target_any = _can_manage_all_carts()
    carts_by_id: dict[int, dict] = {}

    if can_target_any:
        for cart in search_cart_assets(query, limit=75):
            payload = _asset_payload(cart) or {}
            carts_by_id[int(cart["id"])] = payload

        # Ownership rows make owner-name/email searches possible without a Snipe-IT call.
        for row in list_all_owned_carts():
            payload = _ownership_payload(row)
            if query and query not in _cart_search_text(payload):
                continue
            carts_by_id[int(payload["id"])] = payload
    else:
        for row in list_owned_carts(int(user["id"])):
            payload = _ownership_payload(row)
            if query and query not in _cart_search_text(payload):
                continue
            carts_by_id[int(payload["id"])] = payload

    carts = [
        cart for cart in carts_by_id.values()
        if _is_cart_asset(cart) and not _asset_unavailable_reason(cart)
    ]
    carts.sort(key=lambda cart: (
        0 if query and str(cart.get("asset_tag") or "").lower() == query else 1,
        str(cart.get("asset_tag") or "").lower(),
        str(cart.get("name") or "").lower(),
    ))
    return jsonify({
        "ok": True,
        "scope": "all" if can_target_any else "owned",
        "carts": carts[:50],
    })


@bp.get("/api/student-checkouts/lookup")
@login_required
@require_permission(STUDENT_CHECKOUT_PERMISSION)
def api_student_checkout_lookup():
    user = _current_user_profile()
    query = (request.args.get("q") or "").strip()

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    if not query:
        return jsonify({
            "ok": False,
            "error": "Asset Tag or Serial Number is required.",
        }), 400

    try:
        payload = checkout_lookup_payload(query)
    except StudentCheckoutError as exc:
        return _student_checkout_error_response(exc)

    cart = payload.get("cart") or {}
    cart_id = cart.get("id")

    if cart_id and not user_can_access_cart(
        int(cart_id),
        user,
        can_manage_ownership=_can_manage_ownership(),
    ):
        return jsonify({
            "ok": False,
            "error": "You can only check out devices from carts in your Media Catalog scope.",
        }), 403

    return jsonify({
        "ok": True,
        **payload,
    })


@bp.get("/api/student-checkouts")
@login_required
@require_permission("snipeops.media_catalog.view")
def api_student_checkouts():
    user = _current_user_profile()

    if not user:
        return jsonify({
            "ok": False,
            "error": "User profile not found.",
        }), 404

    can_manage_checkouts = (
        _can_manage_student_checkouts()
    )

    can_view_ownership = (
        _can_view_ownership()
    )

    # A user must either be a Student Checkout manager
    # or have Ownership Management visibility.
    if not (
        can_manage_checkouts
        or can_view_ownership
    ):
        return jsonify({
            "ok": False,
            "error": (
                "You do not have permission "
                "to view Student Checkouts."
            ),
        }), 403

    status_filter = (
        request.args.get("status")
        or "active"
    ).strip().lower()

    query = (
        request.args.get("q")
        or ""
    ).strip()

    requested_scope = (
        request.args.get("scope")
        or "mine"
    ).strip().lower()

    # ---------------------------------------------------------
    # Scope
    #
    # mine:
    #   carts assigned directly to current user
    #
    # managed:
    #   every assigned Media Catalog cart
    #
    # Only Ownership Management viewers can use managed scope.
    # ---------------------------------------------------------
    if (
        requested_scope == "managed"
        and can_view_ownership
    ):
        scope_rows = (
            list_all_owned_carts()
        )

        effective_scope = "managed"

    else:
        scope_rows = (
            list_owned_carts(
                int(user["id"])
            )
        )

        effective_scope = "mine"

    cart_ids = [
        int(row["cart_asset_id"])
        for row in scope_rows
        if row.get("cart_asset_id") is not None
    ]

    rows = (
        list_student_checkouts_for_scope(
            cart_asset_ids=cart_ids,
            status_filter=status_filter,
            query=query,
            limit=1500,
        )
        if cart_ids
        else []
    )

    summary = (
        scoped_student_checkout_summary(
            cart_ids
        )
        if cart_ids
        else {
            "active_count": 0,
            "overdue_count": 0,
        }
    )

    return jsonify({
        "ok": True,

        "checkouts": rows,

        "summary": {
            "active_checkout_count":
                summary["active_count"],

            "overdue_checkout_count":
                summary["overdue_count"],
        },

        "scope":
            effective_scope,

        "can_view_managed_scope":
            can_view_ownership,

        "can_manage_student_checkouts":
            can_manage_checkouts,

        "status":
            status_filter,

        "query":
            query,
    })


@bp.post("/api/student-checkouts")
@login_required
@require_permission(STUDENT_CHECKOUT_PERMISSION)
def api_create_student_checkout():
    user = _current_user_profile()
    body = _body()

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    try:
        checkout = create_student_checkout(
            actor_user=user,
            identifier=body.get("identifier") or body.get("asset_identifier"),
            device_id=body.get("device_id") or None,
            student_name=body.get("student_name") or "",
            student_id=body.get("student_id") or "",
            return_by_date=body.get("return_by_date") or None,
            can_manage_ownership=_can_manage_ownership(),
        )
    except StudentCheckoutError as exc:
        return _student_checkout_error_response(exc)

    return jsonify({
        "ok": True,
        "message": "Student Checkout created.",
        "checkout": checkout,
    })


@bp.post("/api/student-checkouts/<int:checkout_id>/return")
@login_required
@require_permission(STUDENT_CHECKOUT_PERMISSION)
def api_return_student_checkout(checkout_id: int):
    user = _current_user_profile()

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    try:
        checkout = return_student_checkout(
            checkout_id=checkout_id,
            actor_user=user,
            can_manage_ownership=_can_manage_ownership(),
        )
    except StudentCheckoutError as exc:
        return _student_checkout_error_response(exc)

    return jsonify({
        "ok": True,
        "message": "Student Checkout returned.",
        "checkout": checkout,
    })


@bp.get("/api/ownership/carts/<int:cart_id>/student-checkouts")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def api_ownership_cart_student_checkouts(cart_id: int):
    user = _current_user_profile()

    if not user:
        return jsonify({"ok": False, "error": "User profile not found."}), 404

    if not user_can_access_cart(
        cart_id,
        user,
        can_manage_ownership=_can_manage_ownership(),
    ):
        return jsonify({
            "ok": False,
            "error": "You do not have access to this cart's Student Checkouts.",
        }), 403

    rows = list_student_checkouts_for_scope(
        cart_asset_ids=[cart_id],
        status_filter="all",
        query="",
        limit=250,
    )

    return jsonify({
        "ok": True,
        "checkouts": rows,
        "can_return": _can_manage_student_checkouts(),
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

    sync_result, sync_error = _sync_cart_metadata_fields(cart, updated or {})
    message = _metadata_message(
        "Cart friendly fields updated.",
        sync_result,
        sync_error,
    )

    log_media_action(
        action="updated_cart_metadata",
        cart_asset=cart,
        device_asset=None,
        ok=True,
        message=message,
        actor_user=user,
    )

    return jsonify({
        "ok": True,
        "message": message,
        "cart": _ownership_payload(updated),
    })

@bp.get("/api/ownership/owners")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def api_ownership_owners():
    owners = list_cart_owners()
    owned_cart_rows = list_all_owned_carts()

    cart_ids = [
        int(row["cart_asset_id"])
        for row in owned_cart_rows
        if row.get("cart_asset_id") is not None
    ]

    device_counts = count_assets_assigned_to_assets(cart_ids)

    totals_by_owner: dict[int, int] = {}

    for row in owned_cart_rows:
        owner_user_id = row.get("owner_user_id")
        cart_asset_id = row.get("cart_asset_id")

        if owner_user_id is None or cart_asset_id is None:
            continue

        owner_id = int(owner_user_id)
        cart_id = int(cart_asset_id)

        totals_by_owner[owner_id] = (
            totals_by_owner.get(owner_id, 0)
            + device_counts.get(cart_id, 0)
        )

    owner_payloads = []

    for owner in owners:
        owner_payload = dict(owner)
        owner_user_id = owner_payload.get("owner_user_id")

        owner_payload["total_devices_managed"] = (
            totals_by_owner.get(int(owner_user_id), 0)
            if owner_user_id is not None
            else 0
        )

        owner_payloads.append(owner_payload)

    district_total = sum(totals_by_owner.values())

    return jsonify({
        "ok": True,
        "owners": owner_payloads,
        "total_devices_managed": district_total,
    })


@bp.get("/api/ownership/users/<int:user_id>/carts")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def api_ownership_user_carts(user_id: int):
    rows = list_owned_carts(user_id)
    carts = _ownership_rows_with_device_counts(rows)

    return jsonify({
        "ok": True,
        "carts": carts,
        "total_devices_managed": sum(
            int(cart.get("device_count") or 0)
            for cart in carts
        ),
    })


@bp.get("/api/ownership/carts")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def api_ownership_all_carts():
    rows = list_all_owned_carts()

    return jsonify({
        "ok": True,
        "carts": _ownership_rows_with_device_counts(rows),
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

    sync_result, sync_error = _sync_cart_metadata_fields(cart, updated or {})
    message = _metadata_message(
        "Cart friendly fields updated by admin.",
        sync_result,
        sync_error,
    )

    log_media_action(
        action="admin_updated_cart_metadata",
        cart_asset=cart,
        device_asset=None,
        ok=True,
        message=message,
        actor_user=actor_user,
    )

    return jsonify({
        "ok": True,
        "message": message,
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

@bp.get("/export/cart/<int:cart_id>.csv")
@login_required
@require_permission("snipeops.media_catalog.view")
def export_cart_csv(cart_id: int):
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
        f"cart-{cart.get('asset_tag') or cart_id}-assets-in-cart-{_export_date_stamp()}.csv"
    )

    return _send_csv(
        _build_carts_csv([payload], include_devices=True),
        filename,
    )


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

@bp.get("/export/all-assigned-carts.csv")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def export_all_assigned_carts_csv():
    mode = (request.args.get("mode") or "carts").strip().lower()
    include_devices = mode in {"devices", "assets", "assigned-assets", "assets-in-carts"}

    rows = list_all_owned_carts()
    payloads = [
        payload
        for row in rows
        if (payload := _cart_export_payload(int(row["cart_asset_id"])))
    ]

    suffix = "assets-in-carts" if include_devices else "carts-only"

    return _send_csv(
        _build_carts_csv(payloads, include_devices=include_devices),
        f"all-assigned-media-carts-{suffix}-{_export_date_stamp()}.csv",
    )


@bp.get("/export/user/<int:user_id>/carts.csv")
@login_required
@require_permission("snipeops.media_catalog.ownership.view")
def export_user_carts_csv(user_id: int):
    owner = get_user_by_id(user_id)

    if not owner:
        return jsonify({"ok": False, "error": "User not found."}), 404

    mode = (request.args.get("mode") or "carts").strip().lower()
    include_devices = mode in {"devices", "assets", "assigned-assets", "assets-in-carts"}

    rows = list_owned_carts(user_id)
    payloads = [
        payload
        for row in rows
        if (payload := _cart_export_payload(int(row["cart_asset_id"])))
    ]

    owner_label = owner.get("display_name") or owner.get("email") or f"user-{user_id}"
    suffix = "assets-in-carts" if include_devices else "carts-only"

    return _send_csv(
        _build_carts_csv(payloads, include_devices=include_devices),
        _safe_filename(f"media-carts-{owner_label}-{suffix}-{_export_date_stamp()}.csv"),
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
