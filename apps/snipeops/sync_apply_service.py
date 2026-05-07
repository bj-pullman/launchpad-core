from apps.snipeops.import_by_scan.snipe import (
    create_asset,
    update_asset,
    checkout_asset_to_user,
)
from apps.snipeops.snipe_catalog.catalog_reader import get_models


def _norm(value):
    return str(value or "").strip()


def _find_model_id(model_name):
    target = _norm(model_name).lower()
    if not target:
        return None

    for model in get_models():
        name = _norm(model.get("name")).lower()
        model_number = _norm(model.get("model_number")).lower()

        if target == name or target == model_number:
            return model.get("id")

    return None


def apply_sync_action(form):
    action = _norm(form.get("sync_action"))
    serial = _norm(form.get("serial"))
    name = _norm(form.get("name"))
    model = _norm(form.get("model"))
    assigned_user = _norm(form.get("assigned_user"))
    snipe_id = _norm(form.get("snipe_id"))

    fallback_model_id = form.get("fallback_model_id", type=int)
    default_status_id = form.get("default_status_id", type=int)
    default_location_id = form.get("default_location_id", type=int)

    if not action:
        raise ValueError("Sync action is required.")

    if action == "create":
        model_id = _find_model_id(model) or fallback_model_id

        if not model_id:
            raise ValueError(f"No matching Snipe-IT model found for '{model}'. Select a fallback model.")

        if not default_status_id or not default_location_id:
            raise ValueError("Default status and location are required to create assets.")

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
        model_id = _find_model_id(model)
        if not model_id:
            raise ValueError(f"No matching Snipe-IT model found for '{model}'.")

        update_asset(
            snipe_id,
            {
                "model_id": int(model_id),
                "name": name,
            },
        )

    if action in {"update_assignment", "update_all"}:
        if not assigned_user:
            raise ValueError("Assigned user is required for assignment update.")

        checkout_asset_to_user(snipe_id, assigned_user)

    if action == "update_model":
        return f"Updated model/name for serial {serial}."

    if action == "update_assignment":
        return f"Updated assignment for serial {serial}."

    if action == "update_all":
        return f"Updated model/name and assignment for serial {serial}."

    raise ValueError(f"Unsupported sync action: {action}")