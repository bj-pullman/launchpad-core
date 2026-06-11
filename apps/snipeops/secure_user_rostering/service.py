from difflib import SequenceMatcher

from modules.core.identity.user_service import list_users

import re

from apps.snipeops.secure_user_rostering.snipe import (
    fetch_users,
    fetch_user,
    fetch_user_assets,
    checkin_asset,
    checkout_asset_to_user,
    delete_user,
)

from apps.snipeops.secure_user_rostering.db import write_audit


STUDENT_EMAIL_RE = re.compile(r"^\d+@sheridanschools\.org$", re.IGNORECASE)

PURGE_CONFIRMATION = "DELETE STUDENTS"
MERGE_CONFIRMATION = "MERGE USERS"

def is_student_account(user):
    email = _lower(user.get("email"))
    username = _lower(user.get("username"))

    return bool(
        STUDENT_EMAIL_RE.match(email)
        or username.isdigit()
    )

def _clean(value):
    return str(value or "").strip()


def _lower(value):
    return _clean(value).lower()


def _display_name(user):
    return (
        _clean(user.get("display_name"))
        or _clean(f"{user.get('first_name') or ''} {user.get('last_name') or ''}")
        or _clean(user.get("email"))
        or _clean(user.get("username"))
    )


def _snipe_name(user):
    return (
        _clean(user.get("name"))
        or _clean(f"{user.get('first_name') or ''} {user.get('last_name') or ''}")
        or _clean(user.get("email"))
        or _clean(user.get("username"))
    )


def _similarity(a, b):
    a = _lower(a)
    b = _lower(b)

    if not a or not b:
        return 0

    return int(SequenceMatcher(None, a, b).ratio() * 100)


def _normalize_snipe_user(user):
    return {
        "id": user.get("id"),
        "name": _snipe_name(user),
        "email": _lower(user.get("email")),
        "username": _lower(user.get("username")),
        "first_name": _clean(user.get("first_name")),
        "last_name": _clean(user.get("last_name")),
        "department": (
            user.get("department", {}).get("name")
            if isinstance(user.get("department"), dict)
            else _clean(user.get("department"))
        ),
        "location": (
            user.get("location", {}).get("name")
            if isinstance(user.get("location"), dict)
            else _clean(user.get("location"))
        ),
        "raw": user,
    }


def _normalize_launchpad_user(user):
    return {
        "id": user.get("id"),
        "name": _display_name(user),
        "email": _lower(user.get("email")),
        "username": _lower(user.get("username")),
        "first_name": _clean(user.get("first_name")),
        "last_name": _clean(user.get("last_name")),
        "department": _clean(user.get("department")),
        "location": _clean(user.get("office_location")),
        "employee_id": _clean(user.get("employee_id")),
        "is_active": int(user.get("is_active") or 0),
        "raw": user,
    }


def build_user_roster_preview():
    launchpad_users = [_normalize_launchpad_user(u) for u in list_users(active_only=False)]
    snipe_users = [_normalize_snipe_user(u) for u in fetch_users()]

    student_users = [u for u in snipe_users if is_student_account(u)]

    snipe_by_email = {u["email"]: u for u in snipe_users if u["email"]}
    snipe_by_username = {u["username"]: u for u in snipe_users if u["username"]}

    matched = []
    missing_in_snipe = []

    for lp_user in launchpad_users:
        match = None
        reason = None

        if lp_user["email"] and lp_user["email"] in snipe_by_email:
            match = snipe_by_email[lp_user["email"]]
            reason = "Email match"
        elif lp_user["username"] and lp_user["username"] in snipe_by_username:
            match = snipe_by_username[lp_user["username"]]
            reason = "Username match"

        if match:
            matched.append({
                "launchpad": lp_user,
                "snipe": match,
                "reason": reason,
            })
        else:
            missing_in_snipe.append(lp_user)

    matched_snipe_ids = {row["snipe"]["id"] for row in matched}
    unmatched_snipe = [u for u in snipe_users if u["id"] not in matched_snipe_ids]

    duplicate_groups = find_like_snipe_accounts(snipe_users, max_name_compare=1000)

    return {
        "counts": {
            "launchpad_users": len(launchpad_users),
            "snipe_users": len(snipe_users),
            "matched": len(matched),
            "missing_in_snipe": len(missing_in_snipe),
            "unmatched_snipe": len(unmatched_snipe),
            "duplicate_groups": len(duplicate_groups),
            "student_users": len(student_users),
        },
        "matched": matched,
        "missing_in_snipe": missing_in_snipe,
        "unmatched_snipe": unmatched_snipe,
        "duplicate_groups": duplicate_groups,
        "student_users": student_users,
    }


def find_like_snipe_accounts(snipe_users=None, max_name_compare=1000):
    users = snipe_users or [_normalize_snipe_user(u) for u in fetch_users()]
    groups = []

    email_groups = {}
    username_groups = {}

    for user in users:
        if user["email"]:
            email_groups.setdefault(user["email"], []).append(user)

        if user["username"]:
            username_groups.setdefault(user["username"], []).append(user)

    grouped_ids = set()

    for reason, lookup in (
        ("Same email", email_groups),
        ("Same username", username_groups),
    ):
        for _, members in lookup.items():
            if len(members) < 2:
                continue

            primary = members[0]
            matches = []

            for member in members[1:]:
                grouped_ids.add(member["id"])
                matches.append({
                    "user": member,
                    "score": 100 if reason == "Same email" else 95,
                    "reasons": [reason],
                })

            groups.append({
                "primary": primary,
                "matches": matches,
            })

    # Name similarity is expensive. Limit it for now.
    name_users = [
        user for user in users
        if user["id"] not in grouped_ids and user["name"]
    ][:max_name_compare]

    seen_pairs = set()

    for index, left in enumerate(name_users):
        matches = []

        left_last = _lower(left.get("last_name"))
        left_first = _lower(left.get("first_name"))

        for right in name_users[index + 1:]:
            pair_key = tuple(sorted([str(left["id"]), str(right["id"])]))

            if pair_key in seen_pairs:
                continue

            seen_pairs.add(pair_key)

            right_last = _lower(right.get("last_name"))
            right_first = _lower(right.get("first_name"))

            # Cheap pre-filter before SequenceMatcher.
            if left_last and right_last and left_last != right_last:
                continue

            if left_first and right_first and left_first[:1] != right_first[:1]:
                continue

            name_score = _similarity(left["name"], right["name"])

            if name_score >= 90:
                matches.append({
                    "user": right,
                    "score": name_score,
                    "reasons": [f"Similar name ({name_score}%)"],
                })

        if matches:
            groups.append({
                "primary": left,
                "matches": sorted(matches, key=lambda m: m["score"], reverse=True),
            })

    return sorted(
        groups,
        key=lambda g: max(m["score"] for m in g["matches"]),
        reverse=True,
    )

def is_student_snipe_user(user):
    email = _lower(user.get("email"))
    return bool(STUDENT_EMAIL_RE.match(email))


def build_student_purge_preview():
    snipe_users = [_normalize_snipe_user(u) for u in fetch_users()]
    student_users = [u for u in snipe_users if is_student_snipe_user(u)]

    return {
        "counts": {
            "student_users": len(student_users),
        },
        "student_users": student_users,
    }


def purge_student_users(*, user_ids, confirmation, batch_limit=100):
    if confirmation != PURGE_CONFIRMATION:
        raise ValueError(f'Type "{PURGE_CONFIRMATION}" to confirm student purge.')

    cleaned_ids = []
    for user_id in user_ids:
        try:
            normalized_id = int(user_id)
        except (TypeError, ValueError):
            continue

        if normalized_id not in cleaned_ids:
            cleaned_ids.append(normalized_id)

    cleaned_ids = cleaned_ids[:batch_limit]

    results = {
        "requested": len(user_ids),
        "processed": 0,
        "deleted": [],
        "skipped": [],
        "errors": [],
    }

    for user_id in cleaned_ids:
        try:
            raw_user = fetch_user(user_id)
            user = _normalize_snipe_user(raw_user)
        except Exception as exc:
            results["errors"].append({
                "user_id": user_id,
                "error": f"Could not fetch Snipe-IT user: {exc}",
            })
            continue

        if not is_student_account(user):
            results["skipped"].append({
                "user_id": user_id,
                "email": user.get("email"),
                "username": user.get("username"),
                "reason": "User does not match student email/username pattern.",
            })
            continue

        checked_in_assets = []
        checkin_errors = []

        try:
            assets = fetch_user_assets(user_id)
        except Exception as exc:
            results["errors"].append({
                "user_id": user_id,
                "email": user.get("email"),
                "error": f"Could not fetch assigned assets: {exc}",
            })
            write_audit(
                action="student_purge",
                status="failed",
                snipe_user_id=user_id,
                details={"error": str(exc), "user": user},
            )
            continue

        for asset in assets:
            asset_id = asset.get("id")

            if not asset_id:
                continue

            try:
                checkin_asset(
                    asset_id=int(asset_id),
                    note="Checked in by Secure User Rostering before student account purge.",
                )
                checked_in_assets.append(asset_id)
            except Exception as exc:
                checkin_errors.append({
                    "asset_id": asset_id,
                    "error": str(exc),
                })

        if checkin_errors:
            results["errors"].append({
                "user_id": user_id,
                "email": user.get("email"),
                "error": "One or more assets failed to check in. User was not deleted.",
                "asset_errors": checkin_errors,
            })
            write_audit(
                action="student_purge",
                status="failed",
                snipe_user_id=user_id,
                asset_count=len(checked_in_assets),
                details={
                    "user": user,
                    "checked_in_assets": checked_in_assets,
                    "checkin_errors": checkin_errors,
                },
            )
            continue

        try:
            delete_user(user_id)

            results["deleted"].append({
                "user_id": user_id,
                "email": user.get("email"),
                "username": user.get("username"),
                "checked_in_assets": checked_in_assets,
            })
            results["processed"] += 1

            write_audit(
                action="student_purge",
                status="success",
                snipe_user_id=user_id,
                asset_count=len(checked_in_assets),
                details={
                    "user": user,
                    "checked_in_assets": checked_in_assets,
                },
            )

        except Exception as exc:
            results["errors"].append({
                "user_id": user_id,
                "email": user.get("email"),
                "error": f"Delete failed after asset check-in: {exc}",
            })

            write_audit(
                action="student_purge",
                status="failed",
                snipe_user_id=user_id,
                asset_count=len(checked_in_assets),
                details={
                    "user": user,
                    "checked_in_assets": checked_in_assets,
                    "error": str(exc),
                },
            )

    return results


def merge_snipe_users(
    *,
    source_user_id,
    target_user_id,
    confirmation,
    delete_source=False,
):
    if confirmation != MERGE_CONFIRMATION:
        raise ValueError(f'Type "{MERGE_CONFIRMATION}" to confirm user merge.')

    source_user_id = int(source_user_id)
    target_user_id = int(target_user_id)

    if source_user_id == target_user_id:
        raise ValueError("Source and target user cannot be the same.")

    moved_assets = []
    errors = []

    assets = fetch_user_assets(source_user_id)

    for asset in assets:
        asset_id = asset.get("id")

        if not asset_id:
            continue

        try:
            checkin_asset(
                asset_id=int(asset_id),
                note=f"Checked in by Secure User Rostering before merge from user {source_user_id} to user {target_user_id}.",
            )

            checkout_asset_to_user(
                asset_id=int(asset_id),
                user_id=target_user_id,
                note=f"Moved by Secure User Rostering merge from user {source_user_id} to user {target_user_id}.",
            )

            moved_assets.append(asset_id)

        except Exception as exc:
            errors.append({
                "asset_id": asset_id,
                "error": str(exc),
            })

    if errors:
        write_audit(
            action="merge_users",
            status="failed",
            snipe_user_id=source_user_id,
            target_snipe_user_id=target_user_id,
            asset_count=len(moved_assets),
            details={
                "moved_assets": moved_assets,
                "errors": errors,
                "delete_source": delete_source,
            },
        )

        return {
            "ok": False,
            "source_user_id": source_user_id,
            "target_user_id": target_user_id,
            "moved_assets": moved_assets,
            "errors": errors,
            "deleted_source": False,
        }

    deleted_source = False

    if delete_source:
        delete_user(source_user_id)
        deleted_source = True

    write_audit(
        action="merge_users",
        status="success",
        snipe_user_id=source_user_id,
        target_snipe_user_id=target_user_id,
        asset_count=len(moved_assets),
        details={
            "moved_assets": moved_assets,
            "delete_source": delete_source,
            "deleted_source": deleted_source,
        },
    )

    return {
        "ok": True,
        "source_user_id": source_user_id,
        "target_user_id": target_user_id,
        "moved_assets": moved_assets,
        "errors": [],
        "deleted_source": deleted_source,
    }