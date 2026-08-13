from __future__ import annotations

from functools import lru_cache
import re

from apps.snipeops.checkout_assets.snipe import _request, _format_snipe_messages


MEDIA_CATALOG_FIELD_LABELS = {
    "teacher_name": "Teacher Name",
    "room_number": "Room Number",
}


def _json_response(response, action: str) -> dict:
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError(f"Snipe-IT {action} returned a non-JSON response.") from exc

    if isinstance(data, dict) and data.get("status") == "error":
        raise ValueError(f"Snipe-IT {action} failed: {_format_snipe_messages(data)}")

    return data


def _rows(endpoint: str, limit: int = 250) -> list[dict]:
    rows: list[dict] = []
    offset = 0

    while True:
        data = _json_response(
            _request("GET", endpoint, params={"limit": limit, "offset": offset}),
            f"GET {endpoint}",
        )

        page_rows = data.get("rows") if isinstance(data, dict) else []
        if not isinstance(page_rows, list):
            return rows

        rows.extend(page_rows)

        total = int(data.get("total") or len(rows))
        if len(rows) >= total or len(page_rows) < limit:
            return rows

        offset += limit


def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _db_column(row: dict) -> str:
    for key in ("db_column", "db_column_name", "db_field", "db_field_name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


@lru_cache(maxsize=1)
def resolve_media_catalog_custom_fields() -> dict[str, str]:
    fields = _rows("/api/v1/fields")
    wanted = {
        _normalize(label): key
        for key, label in MEDIA_CATALOG_FIELD_LABELS.items()
    }

    resolved: dict[str, str] = {}

    for field in fields:
        key = wanted.get(_normalize(field.get("name") or field.get("label")))
        if not key:
            continue

        column = _db_column(field)
        if not column:
            raise ValueError(
                f'Snipe-IT custom field "{MEDIA_CATALOG_FIELD_LABELS[key]}" was found, '
                "but the API did not include its DB field name."
            )

        resolved[key] = column

    missing = [
        label
        for key, label in MEDIA_CATALOG_FIELD_LABELS.items()
        if key not in resolved
    ]

    if missing:
        raise ValueError(
            "Missing Snipe-IT custom field(s): " + ", ".join(missing)
        )

    return resolved


def _unwrap(payload: dict) -> dict:
    if isinstance(payload.get("payload"), dict):
        return payload["payload"]
    if isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def _field_rows(fieldset: dict) -> list[dict]:
    rows: list[dict] = []

    for key in ("fields", "custom_fields", "fieldset_fields"):
        value = fieldset.get(key)

        if isinstance(value, dict):
            value = value.get("rows") or value.get("data") or value.get("items")

        if isinstance(value, list):
            rows.extend([item for item in value if isinstance(item, dict)])

    return rows


def _fieldset_contains_media_fields(fieldset: dict) -> bool:
    wanted_names = {_normalize(label) for label in MEDIA_CATALOG_FIELD_LABELS.values()}
    wanted_columns = set(resolve_media_catalog_custom_fields().values())

    found_names = set()
    found_columns = set()

    for row in _field_rows(fieldset):
        candidates = [row]
        if isinstance(row.get("field"), dict):
            candidates.append(row["field"])

        for candidate in candidates:
            found_names.add(_normalize(candidate.get("name") or candidate.get("label")))
            column = _db_column(candidate)
            if column:
                found_columns.add(column)

    return wanted_names.issubset(found_names) or wanted_columns.issubset(found_columns)


def _fieldset_detail(fieldset_id: int) -> dict:
    return _unwrap(
        _json_response(
            _request("GET", f"/api/v1/fieldsets/{int(fieldset_id)}"),
            "fieldset lookup",
        )
    )


@lru_cache(maxsize=1)
def resolve_media_catalog_fieldset_id() -> int:
    matches: list[int] = []

    for fieldset in _rows("/api/v1/fieldsets"):
        fieldset_id = fieldset.get("id")
        if not fieldset_id:
            continue

        detail = fieldset
        if not _fieldset_contains_media_fields(detail):
            detail = _fieldset_detail(int(fieldset_id))

        if _fieldset_contains_media_fields(detail):
            matches.append(int(fieldset_id))

    if not matches:
        raise ValueError(
            'No Snipe-IT custom fieldset contains both "Teacher Name" and "Room Number".'
        )

    return matches[0]


def _model_detail(model_id: int) -> dict:
    return _unwrap(
        _json_response(
            _request("GET", f"/api/v1/models/{int(model_id)}"),
            "model lookup",
        )
    )


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _model_fieldset_id(model: dict) -> int | None:
    for key in ("fieldset_id", "custom_fieldset_id"):
        parsed = _int_or_none(model.get(key))
        if parsed:
            return parsed

    for key in ("fieldset", "custom_fieldset"):
        value = model.get(key)
        if isinstance(value, dict):
            parsed = _int_or_none(value.get("id"))
            if parsed:
                return parsed

    return None


def ensure_media_catalog_fieldsets_for_assets(assets: list[dict]) -> dict:
    fieldset_id = resolve_media_catalog_fieldset_id()

    model_ids = sorted({
        int(asset["model_id"])
        for asset in assets
        if asset and asset.get("model_id") is not None
    })

    assigned_model_ids: list[int] = []
    already_assigned_model_ids: list[int] = []
    skipped_model_ids: list[int] = []

    for model_id in model_ids:
        model = _model_detail(model_id)
        current_fieldset_id = _model_fieldset_id(model)

        if current_fieldset_id == fieldset_id:
            already_assigned_model_ids.append(model_id)
            continue

        if current_fieldset_id:
            skipped_model_ids.append(model_id)
            continue

        _json_response(
            _request(
                "PATCH",
                f"/api/v1/models/{model_id}",
                json={"fieldset_id": fieldset_id},
            ),
            "model fieldset update",
        )
        assigned_model_ids.append(model_id)

    return {
        "fieldset_id": fieldset_id,
        "assigned_model_ids": assigned_model_ids,
        "already_assigned_model_ids": already_assigned_model_ids,
        "skipped_model_ids": skipped_model_ids,
    }


def update_asset_custom_fields(*, asset_id: int, teacher_name: str, room_number: str) -> dict:
    columns = resolve_media_catalog_custom_fields()

    return _json_response(
        _request(
            "PATCH",
            f"/api/v1/hardware/{int(asset_id)}",
            json={
                columns["teacher_name"]: str(teacher_name or "").strip(),
                columns["room_number"]: str(room_number or "").strip(),
            },
        ),
        "asset custom-field update",
    )


def sync_cart_metadata_to_snipe(
    *,
    cart_asset: dict,
    device_assets: list[dict],
    teacher_name: str,
    room_number: str,
) -> dict:
    assets = [
        asset
        for asset in [cart_asset, *(device_assets or [])]
        if asset and asset.get("id") is not None
    ]

    fieldset_result = ensure_media_catalog_fieldsets_for_assets(assets)

    failures = []
    updated_assets = 0

    for asset in assets:
        try:
            update_asset_custom_fields(
                asset_id=int(asset["id"]),
                teacher_name=teacher_name,
                room_number=room_number,
            )
            updated_assets += 1
        except Exception as exc:
            failures.append(
                f"{asset.get('asset_tag') or asset.get('serial') or asset.get('id')}: {exc}"
            )

    if failures:
        raise ValueError("; ".join(failures[:5]))

    return {
        **fieldset_result,
        "updated_assets": updated_assets,
    }


def checkout_asset_to_cart(*, child_asset_id: int, cart_asset_id: int, note: str) -> dict:
    return _json_response(
        _request(
            "POST",
            f"/api/v1/hardware/{int(child_asset_id)}/checkout",
            json={
                "checkout_to_type": "asset",
                "assigned_asset": int(cart_asset_id),
                "note": note,
            },
        ),
        "checkout",
    )


def checkin_asset(*, asset_id: int, note: str) -> dict:
    return _json_response(
        _request(
            "POST",
            f"/api/v1/hardware/{int(asset_id)}/checkin",
            json={"note": note},
        ),
        "checkin",
    )