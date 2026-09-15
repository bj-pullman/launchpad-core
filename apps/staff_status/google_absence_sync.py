from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from modules.core.identity.user_service import get_user_by_email
from modules.core.settings.settings_service import get_bool_setting, get_setting, set_setting

from .service import (
    PendingAbsenceRequestStateError, StaffStatusValidationError,
    approve_pending_absence_request, create_pending_absence_request_from_public_submission,
    get_pending_absence_request_by_id, get_pending_absence_request_by_submission_uuid,
    reject_pending_absence_request, send_absence_decision_result_email_once,
    send_pending_absence_request_email,
)

LOGGER = logging.getLogger(__name__)
SETTING_PREFIX = "staff_status.absence_google_sync"
CREDENTIAL_ENVIRONMENT_VARIABLE = "STAFF_STATUS_GOOGLE_SERVICE_ACCOUNT_FILE"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DEFAULT_WORKSHEET_NAME = "Absence Requests"
DEFAULT_INTERVAL_MINUTES = 5
DEFAULT_PROCESSING_TIMEOUT_MINUTES = 15
MAX_SAFE_ERROR_LENGTH = 500

BASE_QUEUE_HEADERS = [
    "submission_uuid", "submitted_at", "staff_email", "absence_type", "duration_mode",
    "start_date", "end_date", "start_time", "days_value", "notes", "processing_status",
    "processing_started_at", "processed_at", "launchpad_request_id", "processing_error",
    "processing_attempts", "last_processing_attempt_at", "processing_claim_id",
]
WORKFLOW_HEADERS = [
    "staff_display_name", "department_name", "approval_manager_email", "workflow_status", "reviewed_by", "reviewed_at",
    "decision_note", "launchpad_sync_status", "launchpad_synced_at",
    "launchpad_sync_error", "decision_claim_id",
]
QUEUE_HEADERS = BASE_QUEUE_HEADERS + WORKFLOW_HEADERS


class GoogleAbsenceSyncConfigurationError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (StaffStatusValidationError, PendingAbsenceRequestStateError,
                        GoogleAbsenceSyncConfigurationError)):
        message = str(exc)
    else:
        message = "The request could not be processed. An administrator should review the Launchpad logs."
    return message[:MAX_SAFE_ERROR_LENGTH]


def _parse_positive_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _email_set(value: str | None) -> set[str]:
    return {item.strip().lower() for item in (value or "").split(",") if item.strip()}


def get_google_absence_sync_settings() -> dict:
    credential_path = (os.getenv(CREDENTIAL_ENVIRONMENT_VARIABLE) or "").strip()
    return {
        "enabled": get_bool_setting(f"{SETTING_PREFIX}.enabled", False),
        "spreadsheet_id": (get_setting(f"{SETTING_PREFIX}.spreadsheet_id", "") or "").strip(),
        "worksheet_name": (get_setting(f"{SETTING_PREFIX}.worksheet_name", DEFAULT_WORKSHEET_NAME)
                           or DEFAULT_WORKSHEET_NAME).strip(),
        "review_web_app_url": (get_setting(f"{SETTING_PREFIX}.review_web_app_url", "") or "").strip(),
        "global_reviewer_emails": (get_setting(f"{SETTING_PREFIX}.global_reviewer_emails", "") or "").strip(),
        "interval_minutes": _parse_positive_int(get_setting(f"{SETTING_PREFIX}.interval_minutes", "5"), 5, 5, 1440),
        "processing_timeout_minutes": _parse_positive_int(
            get_setting(f"{SETTING_PREFIX}.processing_timeout_minutes", "15"), 15, 5, 1440),
        "credentials_configured": bool(credential_path and Path(credential_path).is_file()),
        "credential_path_configured": bool(credential_path),
        "last_attempt_at": get_setting(f"{SETTING_PREFIX}.last_attempt_at", "") or "",
        "last_success_at": get_setting(f"{SETTING_PREFIX}.last_success_at", "") or "",
        "last_error": get_setting(f"{SETTING_PREFIX}.last_error", "") or "",
        "last_processed_count": get_setting(f"{SETTING_PREFIX}.last_processed_count", "0") or "0",
        "last_error_count": get_setting(f"{SETTING_PREFIX}.last_error_count", "0") or "0",
    }


def update_google_absence_sync_settings(*, enabled: bool, spreadsheet_id: str,
                                        worksheet_name: str, interval_minutes: int,
                                        processing_timeout_minutes: int,
                                        review_web_app_url: str = "",
                                        global_reviewer_emails: str = "") -> None:
    set_setting(f"{SETTING_PREFIX}.enabled", 1 if enabled else 0)
    set_setting(f"{SETTING_PREFIX}.spreadsheet_id", spreadsheet_id.strip())
    set_setting(f"{SETTING_PREFIX}.worksheet_name", worksheet_name.strip() or DEFAULT_WORKSHEET_NAME)
    set_setting(f"{SETTING_PREFIX}.review_web_app_url", review_web_app_url.strip())
    set_setting(f"{SETTING_PREFIX}.global_reviewer_emails", ",".join(sorted(_email_set(global_reviewer_emails))))
    set_setting(f"{SETTING_PREFIX}.interval_minutes",
                str(_parse_positive_int(interval_minutes, DEFAULT_INTERVAL_MINUTES, 5, 1440)))
    set_setting(f"{SETTING_PREFIX}.processing_timeout_minutes",
                str(_parse_positive_int(processing_timeout_minutes, DEFAULT_PROCESSING_TIMEOUT_MINUTES, 5, 1440)))


class GoogleSheetsAbsenceQueue:
    def __init__(self, *, spreadsheet_id: str, worksheet_name: str, service) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet_name
        self.service = service
        self.headers = QUEUE_HEADERS[:]

    @classmethod
    def from_environment(cls, *, spreadsheet_id: str, worksheet_name: str):
        credential_path = (os.getenv(CREDENTIAL_ENVIRONMENT_VARIABLE) or "").strip()
        if not credential_path:
            raise GoogleAbsenceSyncConfigurationError(f"{CREDENTIAL_ENVIRONMENT_VARIABLE} is not configured.")
        if not Path(credential_path).is_file():
            raise GoogleAbsenceSyncConfigurationError("The configured Google service-account credential file was not found.")
        credentials = service_account.Credentials.from_service_account_file(credential_path, scopes=[SHEETS_SCOPE])
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return cls(spreadsheet_id=spreadsheet_id, worksheet_name=worksheet_name, service=service)

    def _sheet_reference(self) -> str:
        return "'" + self.worksheet_name.replace("'", "''") + "'"

    def fetch_rows(self) -> list[dict]:
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id, range=f"{self._sheet_reference()}!A:AZ",
            majorDimension="ROWS").execute()
        values = result.get("values") or []
        if not values:
            raise GoogleAbsenceSyncConfigurationError("The absence queue worksheet has not been initialized.")
        headers = [str(item).strip() for item in values[0]]
        if headers[:len(BASE_QUEUE_HEADERS)] != BASE_QUEUE_HEADERS or any(h not in headers for h in WORKFLOW_HEADERS):
            raise GoogleAbsenceSyncConfigurationError(
                "The absence queue worksheet is missing required headers. Run initializeAbsenceRequestSheet_().")
        self.headers = headers
        rows = []
        for row_number, values_row in enumerate(values[1:], start=2):
            padded = list(values_row) + [""] * (len(headers) - len(values_row))
            item = dict(zip(headers, padded[:len(headers)]))
            item["_row_number"] = row_number
            rows.append(item)
        return rows

    def fetch_row(self, row_number: int) -> dict:
        end = _column_name(len(self.headers))
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self._sheet_reference()}!A{row_number}:{end}{row_number}",
            majorDimension="ROWS").execute()
        values = (result.get("values") or [[]])[0]
        padded = list(values) + [""] * (len(self.headers) - len(values))
        item = dict(zip(self.headers, padded[:len(self.headers)]))
        item["_row_number"] = row_number
        return item

    def update_row(self, row_number: int, updates: dict) -> None:
        data = []
        for field, value in updates.items():
            if field not in self.headers:
                raise ValueError(f"Unsupported queue field: {field}")
            column_name = _column_name(self.headers.index(field) + 1)
            data.append({"range": f"{self._sheet_reference()}!{column_name}{row_number}",
                         "values": [[value if value is not None else ""]]})
        if data:
            self.service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data}).execute()


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _parse_timestamp(value: str | None) -> datetime | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _is_stale(status: str, started_at: str | None, *, now: datetime, timeout_minutes: int) -> bool:
    if status in {"pending", "error"}:
        return True
    if status not in {"processing", "syncing"}:
        return False
    started = _parse_timestamp(started_at)
    return not started or started <= now - timedelta(minutes=timeout_minutes)


def _validate_queue_identity_fields(row: dict) -> None:
    try:
        uuid.UUID((row.get("submission_uuid") or "").strip())
    except (ValueError, AttributeError):
        raise StaffStatusValidationError("A valid submission id is required.")
    email = (row.get("staff_email") or "").strip().lower()
    if not email.endswith("@sheridanschools.org") or email.count("@") != 1:
        raise StaffStatusValidationError("A valid district email is required.")
    if len(str(row.get("notes") or "").strip()) > 1000:
        raise StaffStatusValidationError("Notes cannot exceed 1000 characters.")


def _payload_from_row(row: dict) -> dict:
    _validate_queue_identity_fields(row)
    return {
        "submission_uuid": (row.get("submission_uuid") or "").strip(),
        "staff_email": (row.get("staff_email") or "").strip().lower(),
        "absence_type": row.get("absence_type") or "", "duration_mode": row.get("duration_mode") or "",
        "start_date": row.get("start_date") or "", "end_date": row.get("end_date") or "",
        "start_time": row.get("start_time") or "",
        "days_value": None if row.get("days_value") == "" else row.get("days_value"),
        "note": str(row.get("notes") or "").strip(),
    }


def _local_workflow_status(record: dict) -> str:
    return "denied" if record.get("status") == "rejected" else str(record.get("status") or "pending")


def _reconciliation_updates(record: dict, attempted_iso: str) -> dict:
    return {
        "launchpad_request_id": record["id"], "approval_manager_email": record.get("approval_manager_email") or "",
        "staff_display_name": record.get("staff_display_name") or "",
        "department_name": record.get("department_name") or "",
        "workflow_status": _local_workflow_status(record), "reviewed_by": record.get("reviewed_by_email") or "",
        "reviewed_at": record.get("reviewed_at") or "", "decision_note": record.get("decision_note") or "",
        "launchpad_sync_status": "synced", "launchpad_synced_at": attempted_iso,
        "launchpad_sync_error": "", "decision_claim_id": "",
    }


def _resolve_reviewer(email: str) -> tuple[int | None, str]:
    user = get_user_by_email(email)
    if user and int(user.get("is_active") or 0) == 1:
        return user["id"], user.get("display_name") or user.get("email") or email
    return None, email


def _process_import(queue, row: dict, attempted_at: datetime, attempted_iso: str, counts: dict) -> None:
    status = (row.get("processing_status") or "").strip().lower()
    if not _is_stale(status, row.get("processing_started_at"), now=attempted_at,
                     timeout_minutes=counts["_timeout"]):
        return
    row_number = int(row["_row_number"])
    claim_id = str(uuid.uuid4())
    try:
        attempts = int(row.get("processing_attempts") or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    queue.update_row(row_number, {"processing_status": "processing", "processing_started_at": attempted_iso,
                                  "processing_error": "", "processing_attempts": attempts,
                                  "last_processing_attempt_at": attempted_iso, "processing_claim_id": claim_id})
    claimed = queue.fetch_row(row_number)
    if claimed.get("processing_claim_id") != claim_id:
        return
    counts["claimed"] += 1
    try:
        record, created = create_pending_absence_request_from_public_submission(payload=_payload_from_row(claimed))
        if not created:
            counts["duplicates"] += 1
        queue.update_row(row_number, {
            "processing_status": "processed", "processed_at": attempted_iso,
            "launchpad_request_id": record["id"], "processing_error": "", "processing_claim_id": "",
            "approval_manager_email": record.get("approval_manager_email") or "",
            "staff_display_name": record.get("staff_display_name") or "",
            "department_name": record.get("department_name") or "",
            "workflow_status": _local_workflow_status(record), "launchpad_sync_status": "synced",
            "launchpad_synced_at": attempted_iso, "launchpad_sync_error": "",
        })
        if created:
            try:
                send_pending_absence_request_email(record)
            except Exception:
                LOGGER.exception("Staff Status approval notification failed for request_id=%s", record.get("id"))
        counts["processed"] += 1
    except StaffStatusValidationError as exc:
        counts["errors"] += 1
        queue.update_row(row_number, {"processing_status": "error", "processing_error": _safe_error(exc),
                                      "processing_claim_id": ""})


def _process_decision(queue, row: dict, attempted_at: datetime, attempted_iso: str,
                      globals_allowed: set[str], counts: dict) -> None:
    workflow = (row.get("workflow_status") or "").strip().lower()
    record = get_pending_absence_request_by_submission_uuid((row.get("submission_uuid") or "").strip())
    if not record:
        return
    row_number = int(row["_row_number"])
    remote_id = str(row.get("launchpad_request_id") or "").strip()
    if remote_id and remote_id != str(record["id"]):
        queue.update_row(row_number, {"launchpad_sync_status": "error",
                                      "launchpad_sync_error": "Launchpad request ID does not match."})
        counts["errors"] += 1
        return
    if record.get("status") != "pending":
        try:
            send_absence_decision_result_email_once(record)
        except Exception:
            queue.update_row(row_number, {"launchpad_sync_status": "error",
                                          "launchpad_sync_error": "The employee result email could not be sent."})
            counts["errors"] += 1
            return
        queue.update_row(row_number, _reconciliation_updates(record, attempted_iso))
        counts["reconciled"] += 1
        return
    if workflow not in {"approved", "denied"}:
        return
    sync_status = (row.get("launchpad_sync_status") or "pending").strip().lower()
    if not _is_stale(sync_status, row.get("reviewed_at"), now=attempted_at,
                     timeout_minutes=counts["_timeout"]):
        return
    reviewer_email = (row.get("reviewed_by") or "").strip().lower()
    manager_email = (record.get("approval_manager_email") or "").strip().lower()
    if not reviewer_email or (reviewer_email != manager_email and reviewer_email not in globals_allowed):
        queue.update_row(row_number, {"launchpad_sync_status": "error",
                                      "launchpad_sync_error": "Reviewer is not authorized for this request.",
                                      "decision_claim_id": ""})
        counts["errors"] += 1
        return
    claim_id = str(uuid.uuid4())
    queue.update_row(row_number, {"launchpad_sync_status": "syncing", "launchpad_sync_error": "",
                                  "decision_claim_id": claim_id})
    claimed = queue.fetch_row(row_number)
    if claimed.get("decision_claim_id") != claim_id:
        return
    reviewer_id, reviewer_name = _resolve_reviewer(reviewer_email)
    reviewed_at = (_parse_timestamp(row.get("reviewed_at")) or attempted_at).isoformat()
    try:
        action = approve_pending_absence_request if workflow == "approved" else reject_pending_absence_request
        record = action(request_id=record["id"], reviewed_by_user_id=reviewer_id,
                        reviewed_by_display_name=reviewer_name, reviewed_by_email=reviewer_email,
                        reviewed_at=reviewed_at, review_source="google_apps_script",
                        decision_note=row.get("decision_note") or None)
        send_absence_decision_result_email_once(record)
        queue.update_row(row_number, _reconciliation_updates(record, attempted_iso))
        counts["decisions"] += 1
    except PendingAbsenceRequestStateError:
        current = get_pending_absence_request_by_id(record["id"])
        queue.update_row(row_number, _reconciliation_updates(current, attempted_iso))
        counts["reconciled"] += 1
    except Exception as exc:
        counts["errors"] += 1
        queue.update_row(row_number, {"launchpad_sync_status": "error",
                                      "launchpad_sync_error": _safe_error(exc), "decision_claim_id": ""})
        LOGGER.exception("Staff Status Google decision failed for request_id=%s", record.get("id"))


def sync_google_absence_requests(*, client=None, now: datetime | None = None) -> dict:
    settings = get_google_absence_sync_settings()
    counts = {"examined": 0, "claimed": 0, "processed": 0, "errors": 0, "duplicates": 0,
              "decisions": 0, "reconciled": 0, "_timeout": settings["processing_timeout_minutes"]}
    if not settings["enabled"]:
        counts.pop("_timeout")
        return {"enabled": False, "counts": counts, "last_sync_utc": None}
    attempted_at = (now or utc_now()).astimezone(timezone.utc)
    attempted_iso = attempted_at.isoformat()
    set_setting(f"{SETTING_PREFIX}.last_attempt_at", attempted_iso)
    try:
        if not settings["spreadsheet_id"]:
            raise GoogleAbsenceSyncConfigurationError("The Google absence spreadsheet ID is not configured.")
        queue = client or GoogleSheetsAbsenceQueue.from_environment(
            spreadsheet_id=settings["spreadsheet_id"], worksheet_name=settings["worksheet_name"])
        rows = queue.fetch_rows()
        for row in rows:
            counts["examined"] += 1
            _process_import(queue, row, attempted_at, attempted_iso, counts)
        for row in queue.fetch_rows():
            _process_decision(queue, row, attempted_at, attempted_iso,
                              _email_set(settings["global_reviewer_emails"]), counts)
        counts.pop("_timeout")
        set_setting(f"{SETTING_PREFIX}.last_success_at", attempted_iso)
        set_setting(f"{SETTING_PREFIX}.last_error", "")
        set_setting(f"{SETTING_PREFIX}.last_processed_count",
                    str(counts["processed"] + counts["decisions"] + counts["reconciled"]))
        set_setting(f"{SETTING_PREFIX}.last_error_count", str(counts["errors"]))
        return {"enabled": True, "counts": counts, "last_sync_utc": attempted_iso}
    except Exception as exc:
        set_setting(f"{SETTING_PREFIX}.last_error", _safe_error(exc))
        set_setting(f"{SETTING_PREFIX}.last_error_count", "1")
        LOGGER.exception("Staff Status Google absence sync failed")
        raise
