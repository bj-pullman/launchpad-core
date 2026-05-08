from apps.snipeops.import_by_scan.snipe import (
    create_asset,
    update_asset,
    checkout_asset_to_user,
)
from apps.snipeops.snipe_catalog.catalog_reader import get_models


def _norm(value):
    return str(value or "").strip()


def _model_key(value):
    return _norm(value).lower().replace("-", "").replace(" ", "")


def _selected_int(value):
    try:
        value = _norm(value)
        return int(value) if value else None
    except Exception:
        return None


def _find_model_id(model_name):
    target = _model_key(model_name)
    if not target:
        return None

    for model in get_models():
        candidates = [
            model.get("name"),
            model.get("model_number"),
        ]

        for candidate in candidates:
            if target == _model_key(candidate):
                return model.get("id")

    return None


def apply_sync_action(form):
    action = _norm(form.get("sync_action"))
    serial = _norm(form.get("serial"))
    name = _norm(form.get("name"))
    model = _norm(form.get("model"))
    assigned_user = _norm(form.get("assigned_user"))
    snipe_id = _norm(form.get("snipe_id"))

    fallback_model_id = _selected_int(form.get("fallback_model_id"))
    default_status_id = _selected_int(form.get("default_status_id"))

    # Used only when creating an asset. This should usually be Technology Office.
    default_location_id = _selected_int(form.get("default_location_id"))

    # Used only when updating an existing asset's current Location field.
    location_id = _selected_int(form.get("location_id"))

    if not action:
        raise ValueError("Sync action is required.")

    if action == "create":
        model_id = _find_model_id(model) or fallback_model_id

        if not model_id:
            raise ValueError(
                f"No matching Snipe-IT model found for '{model}'. Select a Snipe model."
            )

        if not default_status_id or not default_location_id:
            raise ValueError("Default status and default location are required to create assets.")

        result = create_asset(
            {
                "name": name,
                "model_id": model_id,
                "status_id": default_status_id,
                "location_id": default_location_id,
            },
            serial,
        )

        created = result.get("data", {}).get("payload", {}) or {}
        created_id = created.get("id")

        if assigned_user and created_id:
            checkout_asset_to_user(created_id, assigned_user)

        return f"Created asset for serial {serial}."

    if not snipe_id:
        raise ValueError("Snipe asset id is required for update actions.")

    if action in {"update_model", "update_all"}:
        model_id = _find_model_id(model) or fallback_model_id

        if not model_id:
            raise ValueError(
                f"No matching Snipe-IT model found for '{model}'. Select a Snipe model."
            )

        payload = {
            "model_id": int(model_id),
            "name": name,
        }

        if location_id:
            payload["location_id"] = int(location_id)

        update_asset(snipe_id, payload)

    if action in {"update_assignment", "update_all"}:
        if location_id:
            update_asset(
                snipe_id,
                {
                    "location_id": int(location_id),
                },
            )

        if assigned_user:
            checkout_asset_to_user(snipe_id, assigned_user)

    if action == "update_model":
        if location_id:
            return f"Updated model/name and location for serial {serial}."
        return f"Updated model/name for serial {serial}."

    if action == "update_assignment":
        if assigned_user and location_id:
            return f"Updated assignment and location for serial {serial}."
        if location_id:
            return f"Updated location for serial {serial}."
        return f"Updated assignment for serial {serial}."

    if action == "update_all":
        return f"Updated model/name, assignment, and location for serial {serial}."

    raise ValueError(f"Unsupported sync action: {action}")