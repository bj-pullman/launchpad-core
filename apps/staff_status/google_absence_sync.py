from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

from modules.core.settings.settings_service import get_bool_setting, get_setting, set_setting

from .service import (
    StaffStatusValidationError,
    create_pending_absence_request_from_public_submission,
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

QUEUE_HEADERS = [
    "submission_uuid",
    "submitted_at",
    "staff_email",
    "absence_type",
    "duration_mode",
    "start_date",
    "end_date",
    "start_time",
    "days_value",
    "notes",
    "processing_status",
    "processing_started_at",
    "processed_at",
    "launchpad_request_id",
    "processing_error",
    "processing_attempts",
    "last_processing_attempt_at",
    "processing_claim_id",
]


class GoogleAbsenceSyncConfigurationError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (StaffStatusValidationError, GoogleAbsenceSyncConfigurationError)):
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


def get_google_absence_sync_settings() -> dict:
    credential_path = (os.getenv(CREDENTIAL_ENVIRONMENT_VARIABLE) or "").strip()
    return {
        "enabled": get_bool_setting(f"{SETTING_PREFIX}.enabled", False),
        "spreadsheet_id": (get_setting(f"{SETTING_PREFIX}.spreadsheet_id", "") or "").strip(),
        "worksheet_name": (
            get_setting(f"{SETTING_PREFIX}.worksheet_name", DEFAULT_WORKSHEET_NAME)
            or DEFAULT_WORKSHEET_NAME
        ).strip(),
        "interval_minutes": _parse_positive_int(
            get_setting(f"{SETTING_PREFIX}.interval_minutes", str(DEFAULT_INTERVAL_MINUTES)),
            DEFAULT_INTERVAL_MINUTES,
            5,
            1440,
        ),
        "processing_timeout_minutes": _parse_positive_int(
            get_setting(
                f"{SETTING_PREFIX}.processing_timeout_minutes",
                str(DEFAULT_PROCESSING_TIMEOUT_MINUTES),
            ),
            DEFAULT_PROCESSING_TIMEOUT_MINUTES,
            5,
            1440,
        ),
        "credentials_configured": bool(credential_path and Path(credential_path).is_file()),
        "credential_path_configured": bool(credential_path),
        "last_attempt_at": get_setting(f"{SETTING_PREFIX}.last_attempt_at", "") or "",
        "last_success_at": get_setting(f"{SETTING_PREFIX}.last_success_at", "") or "",
        "last_error": get_setting(f"{SETTING_PREFIX}.last_error", "") or "",
        "last_processed_count": get_setting(f"{SETTING_PREFIX}.last_processed_count", "0") or "0",
        "last_error_count": get_setting(f"{SETTING_PREFIX}.last_error_count", "0") or "0",
    }


def update_google_absence_sync_settings(
    *,
    enabled: bool,
    spreadsheet_id: str,
    worksheet_name: str,
    interval_minutes: int,
    processing_timeout_minutes: int,
) -> None:
    set_setting(f"{SETTING_PREFIX}.enabled", 1 if enabled else 0)
    set_setting(f"{SETTING_PREFIX}.spreadsheet_id", spreadsheet_id.strip())
    set_setting(
        f"{SETTING_PREFIX}.worksheet_name",
        worksheet_name.strip() or DEFAULT_WORKSHEET_NAME,
    )
    set_setting(
        f"{SETTING_PREFIX}.interval_minutes",
        str(_parse_positive_int(interval_minutes, DEFAULT_INTERVAL_MINUTES, 5, 1440)),
    )
    set_setting(
        f"{SETTING_PREFIX}.processing_timeout_minutes",
        str(
            _parse_positive_int(
                processing_timeout_minutes,
                DEFAULT_PROCESSING_TIMEOUT_MINUTES,
                5,
                1440,
            )
        ),
    )


class GoogleSheetsAbsenceQueue:
    def __init__(self, *, spreadsheet_id: str, worksheet_name: str, service) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet_name
        self.service = service

    @classmethod
    def from_environment(cls, *, spreadsheet_id: str, worksheet_name: str):
        credential_path = (os.getenv(CREDENTIAL_ENVIRONMENT_VARIABLE) or "").strip()
        if not credential_path:
            raise GoogleAbsenceSyncConfigurationError(
                f"{CREDENTIAL_ENVIRONMENT_VARIABLE} is not configured."
            )
        if not Path(credential_path).is_file():
            raise GoogleAbsenceSyncConfigurationError(
                "The configured Google service-account credential file was not found."
            )

        credentials = service_account.Credentials.from_service_account_file(
            credential_path,
            scopes=[SHEETS_SCOPE],
        )
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return cls(
            spreadsheet_id=spreadsheet_id,
            worksheet_name=worksheet_name,
            service=service,
        )

    def _sheet_reference(self) -> str:
        return "'" + self.worksheet_name.replace("'", "''") + "'"

    def fetch_rows(self) -> list[dict]:
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self._sheet_reference()}!A:Z",
            majorDimension="ROWS",
        ).execute()
        values = result.get("values") or []
        if not values:
            raise GoogleAbsenceSyncConfigurationError(
                "The absence queue worksheet has not been initialized."
            )
        if values[0] != QUEUE_HEADERS:
            raise GoogleAbsenceSyncConfigurationError(
                "The absence queue worksheet headers do not match the required schema."
            )

        rows = []
        for row_number, values_row in enumerate(values[1:], start=2):
            padded = list(values_row) + [""] * (len(QUEUE_HEADERS) - len(values_row))
            item = dict(zip(QUEUE_HEADERS, padded[: len(QUEUE_HEADERS)]))
            item["_row_number"] = row_number
            rows.append(item)
        return rows

    def fetch_row(self, row_number: int) -> dict:
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self._sheet_reference()}!A{row_number}:R{row_number}",
            majorDimension="ROWS",
        ).execute()
        values = (result.get("values") or [[]])[0]
        padded = list(values) + [""] * (len(QUEUE_HEADERS) - len(values))
        item = dict(zip(QUEUE_HEADERS, padded[: len(QUEUE_HEADERS)]))
        item["_row_number"] = row_number
        return item

    def update_row(self, row_number: int, updates: dict) -> None:
        data = []
        for field, value in updates.items():
            if field not in QUEUE_HEADERS:
                raise ValueError(f"Unsupported queue field: {field}")
            column_number = QUEUE_HEADERS.index(field) + 1
            column_name = _column_name(column_number)
            data.append({
                "range": f"{self._sheet_reference()}!{column_name}{row_number}",
                "values": [[value if value is not None else ""]],
            })

        self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()


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


def _is_candidate(row: dict, *, now: datetime, timeout_minutes: int) -> bool:
    status = (row.get("processing_status") or "").strip().lower()
    if status == "pending":
        return True
    if status != "processing":
        return False
    started = _parse_timestamp(row.get("processing_started_at"))
    return not started or started <= now - timedelta(minutes=timeout_minutes)


def _validate_queue_identity_fields(row: dict) -> None:
    try:
        uuid.UUID((row.get("submission_uuid") or "").strip())
    except (ValueError, AttributeError):
        raise StaffStatusValidationError("A valid submission id is required.")

    email = (row.get("staff_email") or "").strip().lower()
    if not email.endswith("@sheridanschools.org") or email.count("@") != 1:
        raise StaffStatusValidationError("A valid district email is required.")

    notes = str(row.get("notes") or "").strip()
    if len(notes) > 1000:
        raise StaffStatusValidationError("Notes cannot exceed 1000 characters.")


def _payload_from_row(row: dict) -> dict:
    _validate_queue_identity_fields(row)
    days_value = row.get("days_value")
    if days_value == "":
        days_value = None
    return {
        "submission_uuid": (row.get("submission_uuid") or "").strip(),
        "staff_email": (row.get("staff_email") or "").strip().lower(),
        "absence_type": row.get("absence_type") or "",
        "duration_mode": row.get("duration_mode") or "",
        "start_date": row.get("start_date") or "",
        "end_date": row.get("end_date") or "",
        "start_time": row.get("start_time") or "",
        "days_value": days_value,
        "note": str(row.get("notes") or "").strip(),
    }


def sync_google_absence_requests(*, client=None, now: datetime | None = None) -> dict:
    settings = get_google_absence_sync_settings()
    counts = {"examined": 0, "claimed": 0, "processed": 0, "errors": 0, "duplicates": 0}
    if not settings["enabled"]:
        return {"enabled": False, "counts": counts, "last_sync_utc": None}

    attempted_at = (now or utc_now()).astimezone(timezone.utc)
    attempted_iso = attempted_at.isoformat()
    set_setting(f"{SETTING_PREFIX}.last_attempt_at", attempted_iso)
    LOGGER.info("Staff Status Google absence sync started")

    try:
        if not settings["spreadsheet_id"]:
            raise GoogleAbsenceSyncConfigurationError(
                "The Google absence spreadsheet ID is not configured."
            )
        queue = client or GoogleSheetsAbsenceQueue.from_environment(
            spreadsheet_id=settings["spreadsheet_id"],
            worksheet_name=settings["worksheet_name"],
        )
        rows = queue.fetch_rows()

        for row in rows:
            counts["examined"] += 1
            if not _is_candidate(
                row,
                now=attempted_at,
                timeout_minutes=settings["processing_timeout_minutes"],
            ):
                continue

            row_number = int(row["_row_number"])
            claim_id = str(uuid.uuid4())
            try:
                attempts = int(row.get("processing_attempts") or 0) + 1
            except (TypeError, ValueError):
                attempts = 1

            queue.update_row(row_number, {
                "processing_status": "processing",
                "processing_started_at": attempted_iso,
                "processing_error": "",
                "processing_attempts": attempts,
                "last_processing_attempt_at": attempted_iso,
                "processing_claim_id": claim_id,
            })
            claimed_row = queue.fetch_row(row_number)
            if claimed_row.get("processing_claim_id") != claim_id:
                continue
            counts["claimed"] += 1

            try:
                request_record, created = create_pending_absence_request_from_public_submission(
                    payload=_payload_from_row(claimed_row),
                )
                if created:
                    try:
                        send_pending_absence_request_email(request_record)
                    except Exception:
                        LOGGER.exception(
                            "Staff Status approval notification failed for request_id=%s",
                            request_record.get("id"),
                        )
                else:
                    counts["duplicates"] += 1

                queue.update_row(row_number, {
                    "processing_status": "processed",
                    "processed_at": attempted_iso,
                    "launchpad_request_id": request_record["id"],
                    "processing_error": "",
                    "processing_claim_id": "",
                })
                counts["processed"] += 1
            except StaffStatusValidationError as exc:
                counts["errors"] += 1
                queue.update_row(row_number, {
                    "processing_status": "error",
                    "processing_error": _safe_error(exc),
                    "processing_claim_id": "",
                })
                LOGGER.warning("Staff Status Google absence row rejected: %s", _safe_error(exc))

        set_setting(f"{SETTING_PREFIX}.last_success_at", attempted_iso)
        set_setting(f"{SETTING_PREFIX}.last_error", "")
        set_setting(f"{SETTING_PREFIX}.last_processed_count", str(counts["processed"]))
        set_setting(f"{SETTING_PREFIX}.last_error_count", str(counts["errors"]))
        LOGGER.info("Staff Status Google absence sync completed: %s", counts)
        return {"enabled": True, "counts": counts, "last_sync_utc": attempted_iso}
    except Exception as exc:
        safe_message = _safe_error(exc)
        set_setting(f"{SETTING_PREFIX}.last_error", safe_message)
        set_setting(f"{SETTING_PREFIX}.last_error_count", "1")
        LOGGER.exception("Staff Status Google absence sync failed")
        raise
