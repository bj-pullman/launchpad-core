from __future__ import annotations

import re
from difflib import SequenceMatcher

from apps.snipeops.snipe_catalog.catalog_db import list_table, list_assets_by_model_ids
from apps.snipeops.snipe_catalog.snipe_api import update_model, update_asset_model, delete_model


GENERIC_MODEL_NAMES = {
    "laptop",
    "desktop",
    "chromebook",
    "printer",
    "monitor",
    "projector",
    "tablet",
    "ipad",
    "switch",
    "phone",
    "camera",
}


def _clean(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _score(a, b):
    a = _clean(a)
    b = _clean(b)

    if not a or not b:
        return 0

    return round(SequenceMatcher(None, a, b).ratio() * 100)


def _model_label(model):
    bits = [
        model.get("manufacturer_name"),
        model.get("name"),
        model.get("model_number"),
    ]
    return " • ".join(str(bit).strip() for bit in bits if str(bit or "").strip())


def _asset_counts_by_model():
    rows = list_table("catalog_assets", limit=100000)
    counts = {}

    for row in rows:
        model_id = row.get("model_id")
        if not model_id:
            continue

        model_id = int(model_id)
        counts[model_id] = counts.get(model_id, 0) + 1

    return counts


def _model_name_flags(model):
    name = str(model.get("name") or "").strip()
    model_number = str(model.get("model_number") or "").strip()
    manufacturer = str(model.get("manufacturer_name") or "").strip()

    flags = []

    clean_name = _clean(name)
    clean_manufacturer = _clean(manufacturer)

    if not name:
        flags.append("Missing model name")
        return flags

    if len(name) <= 3:
        flags.append("Very short model name")

    if clean_name in GENERIC_MODEL_NAMES:
        flags.append("Generic model name")

    if not manufacturer:
        flags.append("Missing manufacturer")

    if model_number and _clean(name) == _clean(model_number):
        flags.append("Name matches model number")

    if clean_manufacturer and clean_name.startswith(clean_manufacturer):
        flags.append("Manufacturer repeated in model name")

    if re.search(r"\s{2,}", name):
        flags.append("Extra spacing")

    if re.search(r"[_]{2,}|[-]{3,}", name):
        flags.append("Repeated separators")

    if re.search(r"\b(test|unknown|n/a|na|none|null)\b", clean_name):
        flags.append("Placeholder name")

    return flags


def build_model_cleanup_queue(min_score=92):
    models = list_table("catalog_models", limit=100000)
    asset_counts = _asset_counts_by_model()

    model_lookup = {int(model["id"]): model for model in models if model.get("id") is not None}

    name_issues = []
    unused_models = []
    exact_model_number_groups = {}
    exact_name_groups = {}
    possible_duplicates = []

    for model in models:
        model_id = int(model.get("id"))
        model["asset_count"] = asset_counts.get(model_id, 0)
        model["display"] = _model_label(model)

        flags = _model_name_flags(model)
        if flags:
            name_issues.append({
                **model,
                "issue_type": "model_name",
                "flags": flags,
                "suggested_name": _suggest_model_name(model),
            })

        if model["asset_count"] == 0:
            unused_models.append({
                **model,
                "issue_type": "unused_model",
                "flags": ["No cached assets assigned to this model"],
            })

        model_number_key = _clean(model.get("model_number"))
        if model_number_key:
            exact_model_number_groups.setdefault(model_number_key, []).append(model)

        exact_name_key = f"{_clean(model.get('manufacturer_name'))}|{_clean(model.get('name'))}"
        if exact_name_key.strip("|"):
            exact_name_groups.setdefault(exact_name_key, []).append(model)

    duplicate_groups = []

    for key, group in exact_model_number_groups.items():
        if len(group) > 1:
            duplicate_groups.append(_build_group("same_model_number", "Same model number", group, 100))

    for key, group in exact_name_groups.items():
        if len(group) > 1:
            duplicate_groups.append(_build_group("same_name", "Same manufacturer and model name", group, 100))

    seen_pairs = set()

    for i, left in enumerate(models):
        for right in models[i + 1:]:
            left_id = int(left.get("id"))
            right_id = int(right.get("id"))
            pair_key = tuple(sorted([left_id, right_id]))

            if pair_key in seen_pairs:
                continue

            if _clean(left.get("manufacturer_name")) != _clean(right.get("manufacturer_name")):
                continue

            left_name = left.get("name") or ""
            right_name = right.get("name") or ""

            score = _score(left_name, right_name)

            if score < int(min_score):
                continue

            # Avoid noisy Chromebook/Laptop number-series matches unless model numbers also match.
            left_number = _clean(left.get("model_number"))
            right_number = _clean(right.get("model_number"))
            if left_number and right_number and left_number != right_number and score < 98:
                continue

            seen_pairs.add(pair_key)
            possible_duplicates.append(_build_group(
                "possible_duplicate",
                "Possible duplicate",
                [left, right],
                score,
            ))

    return {
        "ok": True,
        "summary": {
            "duplicate_groups": len(duplicate_groups) + len(possible_duplicates),
            "model_name_issues": len(name_issues),
            "unused_models": len(unused_models),
        },
        "duplicate_groups": duplicate_groups + possible_duplicates,
        "model_name_issues": name_issues,
        "unused_models": unused_models,
    }


def _build_group(issue_type, reason, models, score):
    models = sorted(
        models,
        key=lambda item: (
            -int(item.get("asset_count") or 0),
            str(item.get("name") or "").lower(),
        ),
    )

    return {
        "issue_type": issue_type,
        "reason": reason,
        "score": score,
        "models": [
            {
                "id": model.get("id"),
                "name": model.get("name"),
                "manufacturer_name": model.get("manufacturer_name"),
                "model_number": model.get("model_number"),
                "asset_count": model.get("asset_count", 0),
                "display": _model_label(model),
            }
            for model in models
        ],
        "suggested_keeper_model_id": models[0].get("id") if models else None,
    }


def _suggest_model_name(model):
    name = str(model.get("name") or "").strip()
    manufacturer = str(model.get("manufacturer_name") or "").strip()

    if manufacturer and _clean(name).startswith(_clean(manufacturer)):
        pattern = re.compile(re.escape(manufacturer), re.IGNORECASE)
        name = pattern.sub("", name, count=1).strip(" -_")

    name = re.sub(r"\s+", " ", name).strip()

    return name


def preview_model_merge(keeper_model_id, source_model_ids):
    keeper_model_id = int(keeper_model_id)
    source_model_ids = [int(item) for item in source_model_ids if int(item) != keeper_model_id]

    if not source_model_ids:
        raise ValueError("Select at least one source model to merge.")

    assets = list_assets_by_model_ids(source_model_ids)

    by_model = {}
    for asset in assets:
        old_model_id = int(asset.get("model_id") or 0)
        by_model.setdefault(old_model_id, []).append(asset)

    return {
        "ok": True,
        "keeper_model_id": keeper_model_id,
        "source_model_ids": source_model_ids,
        "total_assets_to_move": len(assets),
        "assets_by_source_model": {
            str(model_id): len(rows)
            for model_id, rows in by_model.items()
        },
        "sample_assets": assets[:50],
    }


def rename_model(model_id, name=None, model_number=None, manufacturer_id=None, category_id=None):
    result = update_model(
        model_id=model_id,
        name=name,
        model_number=model_number,
        manufacturer_id=manufacturer_id,
        category_id=category_id,
    )

    return {
        "ok": True,
        "message": "Model updated.",
        "result": result,
    }


def merge_models(
    keeper_model_id,
    source_model_ids,
    keeper_updates=None,
    delete_source_models=False,
):
    keeper_model_id = int(keeper_model_id)
    source_model_ids = [int(item) for item in source_model_ids if int(item) != keeper_model_id]
    keeper_updates = keeper_updates or {}

    if not keeper_model_id:
        raise ValueError("Keeper model is required.")

    if not source_model_ids:
        raise ValueError("Select at least one source model.")

    result = {
        "ok": True,
        "keeper_model_id": keeper_model_id,
        "source_model_ids": source_model_ids,
        "keeper_update": None,
        "moved_assets": [],
        "move_failures": [],
        "delete_results": [],
        "delete_failures": [],
    }

    if keeper_updates:
        result["keeper_update"] = update_model(
            model_id=keeper_model_id,
            name=keeper_updates.get("name"),
            model_number=keeper_updates.get("model_number"),
            manufacturer_id=keeper_updates.get("manufacturer_id"),
            category_id=keeper_updates.get("category_id"),
        )

    assets = list_assets_by_model_ids(source_model_ids)

    for asset in assets:
        asset_id = asset.get("id")

        try:
            api_result = update_asset_model(asset_id, keeper_model_id)
            result["moved_assets"].append({
                "asset_id": asset_id,
                "asset_tag": asset.get("asset_tag"),
                "serial": asset.get("serial"),
                "old_model_id": asset.get("model_id"),
                "new_model_id": keeper_model_id,
                "result": api_result,
            })
        except Exception as exc:
            result["move_failures"].append({
                "asset_id": asset_id,
                "asset_tag": asset.get("asset_tag"),
                "serial": asset.get("serial"),
                "old_model_id": asset.get("model_id"),
                "error": str(exc),
            })

    if delete_source_models:
        if result["move_failures"]:
            result["delete_failures"].append({
                "error": "Skipped deleting source models because one or more assets failed to move.",
            })
        else:
            for model_id in source_model_ids:
                try:
                    delete_result = delete_model(model_id)
                    result["delete_results"].append({
                        "model_id": model_id,
                        "result": delete_result,
                    })
                except Exception as exc:
                    result["delete_failures"].append({
                        "model_id": model_id,
                        "error": str(exc),
                    })

    result["message"] = (
        f"Moved {len(result['moved_assets'])} asset(s). "
        f"{len(result['move_failures'])} move failure(s). "
        f"{len(result['delete_results'])} deleted model(s). "
        f"{len(result['delete_failures'])} delete failure(s)."
    )

    return result