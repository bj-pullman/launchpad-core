from __future__ import annotations

from apps.snipeops.checkout_assets.snipe import _request, _format_snipe_messages


def checkout_asset_to_cart(*, child_asset_id: int, cart_asset_id: int, note: str) -> dict:
    response = _request(
        "POST",
        f"/api/v1/hardware/{int(child_asset_id)}/checkout",
        json={
            "checkout_to_type": "asset",
            "assigned_asset": int(cart_asset_id),
            "note": note,
        },
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and data.get("status") == "error":
        raise ValueError(f"Snipe-IT checkout failed: {_format_snipe_messages(data)}")

    return data


def checkin_asset(*, asset_id: int, note: str) -> dict:
    response = _request(
        "POST",
        f"/api/v1/hardware/{int(asset_id)}/checkin",
        json={"note": note},
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and data.get("status") == "error":
        raise ValueError(f"Snipe-IT checkin failed: {_format_snipe_messages(data)}")

    return data