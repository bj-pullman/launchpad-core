from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apps.snipeops.checkout_assets.snipe import build_asset_url
from apps.snipeops.snipe_catalog.catalog_db import (
    get_asset,
    search_assets,
)
from apps.snipeops.media_catalog.media_catalog_db import (
    create_student_checkout_record,
    get_active_student_checkout_for_device,
    get_cart_ownership,
    get_student_checkout,
    list_active_student_checkouts_by_cart_ids,
    list_all_owned_carts,
    list_owned_carts,
    list_student_checkouts,
    log_media_action,
    return_student_checkout_record,
)
from modules.core.settings.settings_service import get_setting


STUDENT_CHECKOUT_PERMISSION = "snipeops.media_catalog.student_checkouts.manage"

ACTIVE_STATUS = "active"
OVERDUE_STATUS = "overdue"
RETURNED_STATUS = "returned"


class StudentCheckoutError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class StudentCheckoutDuplicateError(StudentCheckoutError):
    status_code = 409

    def __init__(self, message: str, existing_checkout: dict | None = None):
        super().__init__(message)
        self.existing_checkout = existing_checkout


class StudentCheckoutNotFoundError(StudentCheckoutError):
    status_code = 404


class StudentCheckoutPermissionError(StudentCheckoutError):
    status_code = 403


def _system_timezone() -> ZoneInfo:
    try:
        name = get_setting("general.timezone", "America/Chicago") or "America/Chicago"
        return ZoneInfo(str(name))
    except Exception:
        return ZoneInfo("America/Chicago")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_datetime(value: datetime | None) -> datetime:
    value = value or _now_utc()

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value


def _local_date(value: datetime | None = None) -> date:
    return _coerce_datetime(value).astimezone(_system_timezone()).date()


def _parse_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    raw = str(value or "").strip()
    if not raw:
        return None

    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def calculate_next_business_day(checkout_day: date) -> date:
    candidate = checkout_day + timedelta(days=1)

    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)

    return candidate


def default_return_by_date(checkout_at: datetime | None = None) -> date:
    return calculate_next_business_day(_local_date(checkout_at))


def is_checkout_overdue(record: dict, *, today: date | None = None) -> bool:
    if record.get("returned_at"):
        return False

    return_by = _parse_date(record.get("return_by_date"))
    if not return_by:
        return False

    today = today or _local_date()
    return today > return_by


def days_overdue(record: dict, *, today: date | None = None) -> int:
    if not is_checkout_overdue(record, today=today):
        return 0

    return_by = _parse_date(record.get("return_by_date"))
    if not return_by:
        return 0

    today = today or _local_date()
    return max(0, (today - return_by).days)


def effective_status(record: dict, *, today: date | None = None) -> str:
    if record.get("returned_at"):
        return RETURNED_STATUS

    if is_checkout_overdue(record, today=today):
        return OVERDUE_STATUS

    return ACTIVE_STATUS


def _status_label(status: str) -> str:
    return {
        ACTIVE_STATUS: "Active",
        OVERDUE_STATUS: "Overdue",
        RETURNED_STATUS: "Returned",
    }.get(status, "Active")


def decorate_checkout(record: dict, *, today: date | None = None) -> dict:
    item = dict(record or {})
    status = effective_status(item, today=today)
    item["stored_status"] = item.get("status") or ACTIVE_STATUS
    item["status"] = status
    item["status_label"] = _status_label(status)
    item["is_overdue"] = status == OVERDUE_STATUS
    item["days_overdue"] = days_overdue(item, today=today)
    item["device_url"] = build_asset_url(item.get("device_asset_id"))
    return item


def asset_payload(asset: dict | None) -> dict | None:
    if not asset:
        return None

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
    }


def _asset_is_cart(asset: dict | None) -> bool:
    if not asset:
        return False

    haystack = " ".join(
        str(asset.get(key) or "")
        for key in ("asset_tag", "name", "category_name", "model_name")
    ).lower()

    return "cart" in haystack


def _asset_status_block_reason(asset: dict) -> str | None:
    status = str(asset.get("status_name") or "").strip().lower()
    if not status:
        return None

    blocked_terms = (
        "archived",
        "archive",
        "retired",
        "disposed",
        "dispose",
        "deleted",
        "lost",
        "stolen",
        "unavailable",
    )

    if any(term in status for term in blocked_terms):
        return f'Device status "{asset.get("status_name")}" is not eligible for Student Checkout.'

    return None


def find_device_by_identifier(identifier: str) -> dict | None:
    query = str(identifier or "").strip()
    if not query:
        return None

    query_lower = query.lower()
    rows = search_assets(query, limit=50)

    for row in rows:
        if str(row.get("asset_tag") or "").strip().lower() == query_lower:
            return row

    for row in rows:
        if str(row.get("serial") or "").strip().lower() == query_lower:
            return row

    candidates = [
        row
        for row in rows
        if query_lower in str(row.get("asset_tag") or "").lower()
        or query_lower in str(row.get("serial") or "").lower()
    ]

    if len(candidates) == 1:
        return candidates[0]

    return None


def cart_context_for_device(device: dict) -> dict:
    cart = None
    ownership = None

    try:
        if str(device.get("assigned_type") or "").lower() == "asset":
            assigned_id = device.get("assigned_id")
            if assigned_id is not None:
                cart = get_asset(int(assigned_id))
    except (TypeError, ValueError):
        cart = None

    if cart and cart.get("id") is not None:
        ownership = get_cart_ownership(int(cart["id"]))

    return {
        "cart": cart,
        "cart_payload": asset_payload(cart),
        "ownership": ownership,
    }


def validate_device_eligibility(device: dict) -> dict:
    if not device:
        raise StudentCheckoutNotFoundError("Device not found.")

    if _asset_is_cart(device):
        raise StudentCheckoutError("Carts cannot be checked out to students.")

    status_reason = _asset_status_block_reason(device)
    if status_reason:
        raise StudentCheckoutError(status_reason)

    context = cart_context_for_device(device)
    cart = context.get("cart")

    if not cart:
        raise StudentCheckoutError(
            "This device is not currently assigned to a cart in the local Snipe-IT catalog."
        )

    if not _asset_is_cart(cart):
        raise StudentCheckoutError(
            "This device is assigned to another asset, but that asset does not appear to be a cart."
        )

    return context


def scoped_cart_rows_for_user(
    user: dict | None,
    *,
    can_manage_ownership: bool = False,
) -> list[dict]:
    """
    Return carts that the authenticated user actually owns/manages.

    Student Checkout scope is based on cart ownership.

    The can_manage_ownership argument is intentionally retained for
    compatibility with existing callers, but Ownership Management permission
    does not expand Student Checkout scope.
    """
    if not user:
        return []

    return list_owned_carts(int(user["id"]))


def scoped_cart_ids_for_user(
    user: dict | None,
    *,
    can_manage_ownership: bool = False,
) -> list[int]:
    """
    Return cart asset IDs owned by the authenticated user.

    Devices inherit Student Checkout management scope from their cart.
    """
    return [
        int(row["cart_asset_id"])
        for row in scoped_cart_rows_for_user(
            user,
            can_manage_ownership=can_manage_ownership,
        )
        if row.get("cart_asset_id") is not None
    ]


def user_can_access_cart(
    cart_asset_id: int | None,
    user: dict | None,
    *,
    can_manage_ownership: bool = False,
) -> bool:
    """
    Determine whether the authenticated user manages this cart.

    Ownership Management permission does NOT grant Student Checkout access
    to every cart. A user manages a device for Student Checkout only when
    the device belongs to a cart assigned to that user.

    can_manage_ownership is retained for compatibility with existing callers
    but intentionally does not bypass ownership.
    """
    if not cart_asset_id or not user:
        return False

    ownership = get_cart_ownership(int(cart_asset_id))

    if not ownership:
        return False

    try:
        return int(ownership.get("owner_user_id") or 0) == int(user["id"])
    except (TypeError, ValueError):
        return False


def assert_checkout_scope(
    record: dict,
    user: dict | None,
    *,
    can_manage_ownership: bool = False,
) -> None:
    """
    Enforce Student Checkout ownership scope.

    A checkout is manageable only when its originating cart is currently
    assigned to the authenticated user.
    """
    if user_can_access_cart(
        record.get("original_cart_asset_id"),
        user,
        can_manage_ownership=can_manage_ownership,
    ):
        return

    raise StudentCheckoutPermissionError(
        "You do not have access to Student Checkouts for this cart."
    )


def checkout_lookup_payload(identifier: str) -> dict:
    device = find_device_by_identifier(identifier)

    if not device:
        raise StudentCheckoutNotFoundError(
            "Device not found by Asset Tag or Serial Number."
        )

    active = get_active_student_checkout_for_device(int(device["id"]))
    context = cart_context_for_device(device)

    eligible = True
    reason = ""

    try:
        context = validate_device_eligibility(device)
    except StudentCheckoutError as exc:
        eligible = False
        reason = exc.message

    return {
        "device": asset_payload(device),
        "cart": context.get("cart_payload"),
        "ownership": context.get("ownership"),
        "eligible": eligible,
        "eligibility_message": reason,
        "active_checkout": decorate_checkout(active) if active else None,
        "default_return_by_date": default_return_by_date().isoformat(),
    }


def create_student_checkout(
    *,
    actor_user: dict,
    identifier: str | None = None,
    device_id: int | None = None,
    student_name: str,
    student_id: str | None = None,
    return_by_date: str | date | None = None,
    can_manage_ownership: bool = False,
    now: datetime | None = None,
) -> dict:
    student_name = str(student_name or "").strip()
    student_id = str(student_id or "").strip()

    if not student_name:
        raise StudentCheckoutError("Student Name is required.")

    if device_id is not None:
        try:
            device = get_asset(int(device_id))
        except (TypeError, ValueError):
            raise StudentCheckoutError("Invalid device id.") from None
    else:
        device = find_device_by_identifier(identifier or "")

    if not device:
        raise StudentCheckoutNotFoundError(
            "Device not found by Asset Tag or Serial Number."
        )

    # First validate that this is actually an eligible device assigned
    # to a valid cart.
    context = validate_device_eligibility(device)

    cart = context["cart"]
    ownership = context.get("ownership") or {}

    # Student Checkout management follows cart ownership.
    #
    # Having Ownership Management permission does not grant checkout
    # authority over every cart.
    if not user_can_access_cart(
        int(cart["id"]),
        actor_user,
        can_manage_ownership=can_manage_ownership,
    ):
        raise StudentCheckoutPermissionError(
            "This device belongs to a cart that is not assigned to you."
        )

    # Only after scope has been established should we expose information
    # about an existing Student Checkout.
    active = get_active_student_checkout_for_device(int(device["id"]))

    if active:
        existing = decorate_checkout(active)

        raise StudentCheckoutDuplicateError(
            (
                f"This device is currently checked out to "
                f"{existing.get('student_name') or 'another student'} "
                "and must be returned before it can be checked out again."
            ),
            existing_checkout=existing,
        )

    checkout_at = _coerce_datetime(now)
    checkout_day = _local_date(checkout_at)

    default_due = calculate_next_business_day(checkout_day)
    return_by = _parse_date(return_by_date) or default_due

    if return_by < checkout_day:
        raise StudentCheckoutError(
            "Return By date cannot be before the checkout date."
        )

    due_date_overridden = return_by != default_due

    actor_display = (
        actor_user.get("display_name")
        or actor_user.get("email")
        or ""
    )

    payload = {
        "device_asset_id": int(device["id"]),
        "device_asset_tag": device.get("asset_tag") or "",
        "device_serial": device.get("serial") or "",
        "device_name": device.get("name") or "",
        "device_model_name": device.get("model_name") or "",
        "device_status_name": device.get("status_name") or "",

        "original_cart_asset_id": int(cart["id"]),
        "original_cart_asset_tag": cart.get("asset_tag") or "",
        "original_cart_name": cart.get("name") or "",

        "original_cart_teacher_name": (
            ownership.get("teacher_name") or ""
        ),
        "original_cart_room_number": (
            ownership.get("room_number") or ""
        ),

        "original_owner_user_id": ownership.get("owner_user_id"),
        "original_owner_email": ownership.get("owner_email") or "",
        "original_owner_display_name": (
            ownership.get("owner_display_name") or ""
        ),

        "student_name": student_name,
        "student_id": student_id,

        "checked_out_at": (
            checkout_at
            .astimezone(timezone.utc)
            .isoformat()
        ),

        "return_by_date": return_by.isoformat(),

        "checkout_actor_user_id": actor_user.get("id"),
        "checkout_actor_email": actor_user.get("email") or "",
        "checkout_actor_display_name": actor_display,

        "status": ACTIVE_STATUS,
        "due_date_overridden": due_date_overridden,
    }

    try:
        record = create_student_checkout_record(payload)

    except sqlite3.IntegrityError as exc:
        # Keep the database unique index as the final line of defense
        # against two simultaneous active checkouts.
        active = get_active_student_checkout_for_device(
            int(device["id"])
        )

        raise StudentCheckoutDuplicateError(
            (
                "This device already has an active Student Checkout "
                "and must be returned first."
            ),
            existing_checkout=(
                decorate_checkout(active)
                if active
                else None
            ),
        ) from exc

    message = (
        f"Checked out "
        f"{device.get('asset_tag') or device.get('serial') or device.get('id')} "
        f"to {student_name}; due {return_by.isoformat()}."
    )

    if due_date_overridden:
        message += " Return By date was manually overridden."

    log_media_action(
        action="student_checkout_created",
        cart_asset=cart,
        device_asset=device,
        ok=True,
        message=message,
        actor_user=actor_user,
    )

    return decorate_checkout(record)


def return_student_checkout(
    *,
    checkout_id: int,
    actor_user: dict,
    can_manage_ownership: bool = False,
    now: datetime | None = None,
) -> dict:
    record = get_student_checkout(int(checkout_id))

    if not record:
        raise StudentCheckoutNotFoundError("Student Checkout record not found.")

    if record.get("returned_at"):
        raise StudentCheckoutError("This Student Checkout has already been returned.")

    assert_checkout_scope(
        record,
        actor_user,
        can_manage_ownership=can_manage_ownership,
    )

    returned_at = _coerce_datetime(now).astimezone(timezone.utc).isoformat()

    updated = return_student_checkout_record(
        checkout_id=int(checkout_id),
        actor_user=actor_user,
        returned_at=returned_at,
    )

    if not updated:
        raise StudentCheckoutNotFoundError("Student Checkout record not found.")

    cart = (
        get_asset(int(updated["original_cart_asset_id"]))
        if updated.get("original_cart_asset_id") is not None
        else None
    )

    device = (
        get_asset(int(updated["device_asset_id"]))
        if updated.get("device_asset_id") is not None
        else None
    )

    message = (
        f"Returned {updated.get('device_asset_tag') or updated.get('device_serial') or updated.get('device_asset_id')} "
        f"from {updated.get('student_name') or 'student'}."
    )

    log_media_action(
        action="student_checkout_returned",
        cart_asset=cart,
        device_asset=device,
        ok=True,
        message=message,
        actor_user=actor_user,
    )

    return decorate_checkout(updated)


def _checkout_matches_query(record: dict, query: str) -> bool:
    if not query:
        return True

    haystack = " ".join(
        str(record.get(key) or "")
        for key in (
            "device_asset_tag",
            "device_serial",
            "device_name",
            "device_model_name",
            "student_name",
            "student_id",
            "original_cart_asset_tag",
            "original_cart_name",
            "original_cart_teacher_name",
            "original_cart_room_number",
            "original_owner_email",
            "original_owner_display_name",
            "checked_out_at",
            "return_by_date",
            "returned_at",
            "status",
            "status_label",
        )
    ).lower()

    return query.lower() in haystack


def list_student_checkouts_for_scope(
    *,
    cart_asset_ids: list[int],
    status_filter: str = ACTIVE_STATUS,
    query: str = "",
    limit: int = 1000,
    today: date | None = None,
) -> list[dict]:
    status_filter = (status_filter or ACTIVE_STATUS).strip().lower()
    query = str(query or "").strip()

    rows = [
        decorate_checkout(row, today=today)
        for row in list_student_checkouts(
            cart_asset_ids=cart_asset_ids,
            limit=limit,
        )
    ]

    if status_filter == ACTIVE_STATUS:
        rows = [row for row in rows if row["status"] in {ACTIVE_STATUS, OVERDUE_STATUS}]
    elif status_filter == OVERDUE_STATUS:
        rows = [row for row in rows if row["status"] == OVERDUE_STATUS]
    elif status_filter == RETURNED_STATUS:
        rows = [row for row in rows if row["status"] == RETURNED_STATUS]
    elif status_filter != "all":
        rows = [row for row in rows if row["status"] in {ACTIVE_STATUS, OVERDUE_STATUS}]

    if query:
        rows = [row for row in rows if _checkout_matches_query(row, query)]

    return rows


def checkout_counts_for_cart_ids(
    cart_asset_ids: list[int],
    *,
    today: date | None = None,
) -> dict[int, dict]:
    rows = [
        decorate_checkout(row, today=today)
        for row in list_active_student_checkouts_by_cart_ids(cart_asset_ids)
    ]

    summary: dict[int, dict] = {
        int(cart_id): {
            "active_count": 0,
            "overdue_count": 0,
            "checkouts": [],
        }
        for cart_id in cart_asset_ids
        if cart_id is not None
    }

    for row in rows:
        cart_id = row.get("original_cart_asset_id")
        if cart_id is None:
            continue

        bucket = summary.setdefault(
            int(cart_id),
            {
                "active_count": 0,
                "overdue_count": 0,
                "checkouts": [],
            },
        )

        bucket["active_count"] += 1
        if row["status"] == OVERDUE_STATUS:
            bucket["overdue_count"] += 1
        bucket["checkouts"].append(row)

    return summary


def attach_checkout_summaries_to_carts(carts: list[dict]) -> list[dict]:
    cart_ids = [
        int(cart["id"])
        for cart in carts
        if cart.get("id") is not None
    ]

    summaries = checkout_counts_for_cart_ids(cart_ids)

    for cart in carts:
        cart_id = cart.get("id")
        cart["student_checkout_summary"] = (
            summaries.get(
                int(cart_id),
                {
                    "active_count": 0,
                    "overdue_count": 0,
                    "checkouts": [],
                },
            )
            if cart_id is not None
            else {
                "active_count": 0,
                "overdue_count": 0,
                "checkouts": [],
            }
        )

    return carts


def scoped_student_checkout_summary(cart_asset_ids: list[int]) -> dict:
    summaries = checkout_counts_for_cart_ids(cart_asset_ids)
    active_count = sum(item["active_count"] for item in summaries.values())
    overdue_count = sum(item["overdue_count"] for item in summaries.values())

    return {
        "active_count": active_count,
        "overdue_count": overdue_count,
    }


def recent_student_checkout_activity(
    *,
    cart_asset_ids: list[int],
    limit: int = 8,
) -> list[dict]:
    return [
        decorate_checkout(row)
        for row in list_student_checkouts(
            cart_asset_ids=cart_asset_ids,
            limit=limit,
        )
    ][:limit]
