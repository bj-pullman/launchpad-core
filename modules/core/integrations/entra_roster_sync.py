from modules.core.auth.user_admin_service import (
    create_sso_stub_user,
    get_local_user_by_user_id,
    update_local_user,
)
from modules.core.identity.identity_db import get_connection as get_identity_connection
from modules.core.identity.user_service import (
    get_user_by_email,
    normalize_email,
    create_user,
    update_user,
)
from modules.core.integrations.entra_client import list_entra_users
from modules.core.integrations.sync_run_service import start_sync_run, finish_sync_run
from modules.core.utils.time import utc_now_iso


SYNC_KEY = "entra_launchpad_users"

COMPARE_FIELDS = [
    "source_type",
    "source_id",
    "email",
    "username",
    "display_name",
    "first_name",
    "last_name",
    "is_active",
    "job_title",
    "department",
    "office_location",
    "company_name",
    "employee_id",
    "preferred_language",
    "business_phone",
    "mobile_phone",
    "manager_source_id",
    "manager_email",
    "manager_display_name",
]


def _first_business_phone(graph_user: dict) -> str | None:
    phones = graph_user.get("businessPhones") or []
    if isinstance(phones, list) and phones:
        return phones[0]
    return None


def _graph_user_to_launchpad_payload(graph_user: dict) -> dict:
    email = normalize_email(graph_user.get("mail") or graph_user.get("userPrincipalName"))

    return {
        "source_type": "entra",
        "source_id": graph_user.get("id"),
        "email": email,
        "username": email,
        "display_name": graph_user.get("displayName"),
        "first_name": graph_user.get("givenName"),
        "last_name": graph_user.get("surname"),
        "is_active": 1 if graph_user.get("accountEnabled") else 0,
        "job_title": graph_user.get("jobTitle"),
        "department": graph_user.get("department"),
        "office_location": graph_user.get("officeLocation"),
        "company_name": graph_user.get("companyName"),
        "employee_id": graph_user.get("employeeId"),
        "preferred_language": graph_user.get("preferredLanguage"),
        "business_phone": _first_business_phone(graph_user),
        "mobile_phone": graph_user.get("mobilePhone"),
        "manager_source_id": None,
        "manager_email": None,
        "manager_display_name": None,
        "last_synced_at": utc_now_iso(),
    }


def _normal(value):
    if value is None:
        return ""
    return str(value).strip()


def _user_has_changes(existing_user: dict, payload: dict) -> bool:
    for field in COMPARE_FIELDS:
        if field == "is_active":
            if int(existing_user.get(field) or 0) != int(payload.get(field) or 0):
                return True
            continue

        if _normal(existing_user.get(field)) != _normal(payload.get(field)):
            return True

    return False


def _sync_local_auth_state(user_id: int, username: str, is_active: int) -> bool:
    local_account = get_local_user_by_user_id(user_id)

    if not local_account:
        create_sso_stub_user(
            user_id=user_id,
            username=username,
            is_active=is_active,
        )
        return True

    local_username = (local_account.get("username") or username or "").strip().lower()
    local_active = int(local_account.get("is_active") or 0)

    if local_username != username or local_active != int(is_active):
        update_local_user(user_id, username, is_active)
        return True

    return False


def _disable_removed_entra_users(current_source_ids: set[str]) -> int:
    if not current_source_ids:
        return 0

    disabled_count = 0
    now = utc_now_iso()

    with get_identity_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM users
            WHERE source_type = 'entra'
              AND is_active = 1
            """
        ).fetchall()

    for row in rows:
        user = dict(row)
        source_id = (user.get("source_id") or "").strip()

        if source_id in current_source_ids:
            continue

        payload = {
            **user,
            "is_active": 0,
            "last_synced_at": now,
        }

        update_user(user["id"], payload)

        username = (
            user.get("email")
            or user.get("username")
            or ""
        ).strip().lower()

        if username:
            _sync_local_auth_state(user["id"], username, 0)

        disabled_count += 1

    return disabled_count


def sync_entra_users_to_launchpad(trigger_type: str = "manual") -> dict:
    run_id = start_sync_run(
        sync_key=SYNC_KEY,
        source_system="entra",
        target_system="launchpad",
        trigger_type=trigger_type,
    )

    created_count = 0
    updated_count = 0
    unchanged_count = 0
    skipped_count = 0
    error_count = 0
    deactivated_count = 0
    errors = []
    current_source_ids = set()

    try:
        graph_users = list_entra_users()

        for graph_user in graph_users:
            try:
                payload = _graph_user_to_launchpad_payload(graph_user)

                if not payload["email"]:
                    skipped_count += 1
                    continue

                if payload["source_id"]:
                    current_source_ids.add(str(payload["source_id"]))

                existing_user = get_user_by_email(payload["email"])

                if not existing_user:
                    saved_user = create_user(payload)
                    _sync_local_auth_state(
                        user_id=saved_user["id"],
                        username=payload["email"],
                        is_active=payload["is_active"],
                    )
                    created_count += 1
                    continue

                user_changed = _user_has_changes(existing_user, payload)
                auth_changed = _sync_local_auth_state(
                    user_id=existing_user["id"],
                    username=payload["email"],
                    is_active=payload["is_active"],
                )

                if user_changed:
                    update_user(existing_user["id"], payload)

                if user_changed or auth_changed:
                    updated_count += 1
                else:
                    unchanged_count += 1

            except Exception as exc:
                error_count += 1
                errors.append(str(exc))

        deactivated_count = _disable_removed_entra_users(current_source_ids)
        updated_count += deactivated_count

        status = "success" if error_count == 0 else "completed_with_errors"

        message = (
            f"Entra user sync completed. "
            f"Created: {created_count}, updated: {updated_count}, "
            f"unchanged: {unchanged_count}, skipped: {skipped_count}, "
            f"deactivated: {deactivated_count}, errors: {error_count}."
        )

        if errors:
            message += " Errors: " + " | ".join(errors[:10])

        finish_sync_run(
            run_id,
            status=status,
            created_count=created_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            skipped_count=skipped_count,
            error_count=error_count,
            message=message,
        )

        return {
            "ok": error_count == 0,
            "status": status,
            "created": created_count,
            "updated": updated_count,
            "unchanged": unchanged_count,
            "skipped": skipped_count,
            "deactivated": deactivated_count,
            "errors": error_count,
            "message": message,
        }

    except Exception as exc:
        finish_sync_run(
            run_id,
            status="failed",
            created_count=created_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            skipped_count=skipped_count,
            error_count=error_count + 1,
            message=str(exc),
        )
        raise