from apps.snipeops.import_by_scan.snipe import find_asset_by_serial
from apps.snipeops.mapping_service import list_mappings


def _norm(value):
    return str(value or "").strip()


def _norm_lower(value):
    return _norm(value).lower()


def _normalize_person(value):
    return (
        _norm_lower(value)
        .replace("@sheridanschools.org", "")
        .replace(".", "")
        .replace(" ", "")
    )


def _users_match(source_user, snipe_user):
    source_raw = _norm(source_user)
    snipe_raw = _norm(snipe_user)

    if not source_raw or not snipe_raw:
        return True

    return _normalize_person(source_raw) == _normalize_person(snipe_raw)


def _load_mapping_lookup(source):
    mappings = list_mappings(source=source) + list_mappings(source="any")

    lookup = {}
    for item in mappings:
        field = _norm_lower(item.get("field"))
        raw = _norm_lower(item.get("raw_value"))
        mapped = _norm(item.get("mapped_value"))

        if field and raw and mapped:
            lookup[(field, raw)] = mapped

    return lookup


def _apply_mappings(device):
    source = _norm_lower(device.get("source"))
    lookup = _load_mapping_lookup(source)

    mapped = dict(device)
    mapping_notes = []

    field_map = {
        "model": "model",
        "manufacturer": "manufacturer",
        "os_version": "os_version",
        "device_type": "device_type",
    }

    for source_field, mapping_field in field_map.items():
        raw_value = _norm(device.get(source_field))
        mapped_value = lookup.get((mapping_field, _norm_lower(raw_value)))

        if mapped_value and mapped_value != raw_value:
            mapped[source_field] = mapped_value
            mapping_notes.append({
                "field": mapping_field,
                "from": raw_value,
                "to": mapped_value,
            })

    mapped["mapping_notes"] = mapping_notes
    return mapped


def _snipe_model_name(snipe):
    model = snipe.get("model") or {}
    if isinstance(model, dict):
        return model.get("name") or ""
    return ""


def _snipe_manufacturer_name(snipe):
    manufacturer = snipe.get("manufacturer") or {}
    if isinstance(manufacturer, dict):
        return manufacturer.get("name") or ""
    return ""


def _snipe_assigned_user(snipe):
    assigned_to = snipe.get("assigned_to") or {}
    if not isinstance(assigned_to, dict):
        return ""

    return (
        assigned_to.get("email")
        or assigned_to.get("username")
        or assigned_to.get("name")
        or ""
    )


def _compare_fields(source, snipe):
    diffs = []

    model_source = _norm(source.get("model"))
    model_snipe = _norm(_snipe_model_name(snipe))

    if model_source and model_snipe and _norm_lower(model_source) != _norm_lower(model_snipe):
        diffs.append({
            "field": "model_reference",
            "label": "Model reference",
            "source": model_source,
            "snipe": model_snipe,
            "actionable": False,
        })

    manufacturer_source = _norm(source.get("manufacturer"))
    manufacturer_snipe = _norm(_snipe_manufacturer_name(snipe))

    if (
        manufacturer_source
        and manufacturer_snipe
        and _norm_lower(manufacturer_source) != _norm_lower(manufacturer_snipe)
    ):
        diffs.append({
            "field": "manufacturer_reference",
            "label": "Manufacturer reference",
            "source": manufacturer_source,
            "snipe": manufacturer_snipe,
            "actionable": False,
        })

    source_user = _norm(source.get("assigned_user"))
    snipe_user = _norm(_snipe_assigned_user(snipe))

    if source_user and snipe_user and not _users_match(source_user, snipe_user):
        diffs.append({
            "field": "assigned_user",
            "label": "Assigned user",
            "source": source_user,
            "snipe": snipe_user,
            "actionable": True,
        })

    return diffs


def build_sync_preview(source_devices):
    results = []

    for raw_device in source_devices:
        device = _apply_mappings(raw_device)

        serial = device.get("serial")
        snipe_asset = find_asset_by_serial(serial)

        if not snipe_asset:
            results.append({
                **device,
                "status": "create",
                "diffs": [],
                "diff_fields": [],
                "snipe_id": None,
                "snipe_asset_tag": None,
                "snipe_name": "",
            })
            continue

        diffs = _compare_fields(device, snipe_asset)
        actionable_diffs = [item for item in diffs if item.get("actionable", True)]
        diff_fields = [item["field"] for item in actionable_diffs]

        results.append({
            **device,
            "status": "update" if actionable_diffs else "match",
            "diffs": diffs,
            "diff_fields": diff_fields,
            "snipe_id": snipe_asset.get("id"),
            "snipe_asset_tag": snipe_asset.get("asset_tag"),
            "snipe_name": snipe_asset.get("name") or "",
        })

    summary = {
        "total": len(results),
        "create": len([r for r in results if r["status"] == "create"]),
        "update": len([r for r in results if r["status"] == "update"]),
        "match": len([r for r in results if r["status"] == "match"]),
    }

    return {
        "summary": summary,
        "results": results,
    }