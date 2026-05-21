import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import urlopen, Request

from modules.core.settings.settings_service import get_setting

from .maintenance_db import list_backup_records, upsert_backup_metadata

PUBLIC_RELEASE_MANIFEST_URL = os.getenv(
    "LAUNCHPAD_RELEASE_MANIFEST_URL",
    "https://raw.githubusercontent.com/bj-pullman/launchpad-core/main/release_manifest.json",
)

DEFAULT_BACKUP_ROOT = r"C:\launchpad-backups"


def get_app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_backup_root() -> Path:
    return Path(os.getenv("LAUNCHPAD_BACKUP_ROOT", DEFAULT_BACKUP_ROOT))


def _load_json_file(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_json_text(value: str):
    return json.loads((value or "").lstrip("\ufeff"))


def _parse_backup_timestamp(value: str):
    value = (value or "").strip()

    for fmt in ("%Y-%m-%d_%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    return None


def _format_date(dt: datetime, date_format: str):
    if date_format == "ymd":
        return dt.strftime("%Y-%m-%d")

    if date_format == "dmy":
        return dt.strftime("%d/%m/%Y")

    return dt.strftime("%m/%d/%Y")


def _format_time(dt: datetime, time_format: str):
    if time_format == "24h":
        return dt.strftime("%H:%M")

    return dt.strftime("%I:%M %p").lstrip("0")


def _format_backup_created_at(timestamp: str):
    dt = _parse_backup_timestamp(timestamp)

    if not dt:
        return timestamp or "Unknown"

    timezone_name = get_setting("general.timezone", "America/Chicago")
    date_format = get_setting("general.date_format", "mdy")
    time_format = get_setting("general.time_format", "12h")

    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")

    dt = dt.replace(tzinfo=tz)

    return f"{_format_date(dt, date_format)} {_format_time(dt, time_format)}"


def _decorate_backup_record(record: dict):
    record["created_display"] = _format_backup_created_at(record.get("timestamp"))
    record["snapshot_display"] = "Full app" if record.get("include_app_snapshot") else "Core backup"
    record["database_count"] = record.get("database_count") or 0
    record["protected_file_count"] = record.get("protected_file_count") or 0
    record["status_display"] = "OK" if record.get("ok") else "Issue"
    return record


def list_backups(limit: int = 20):
    return [
        _decorate_backup_record(record)
        for record in list_backup_records(limit=limit)
    ]


def _run_powershell_script(script_name: str, args: list[str], timeout: int = 900):
    app_root = get_app_root()
    script_path = app_root / "scripts" / script_name

    if not script_path.exists():
        return {
            "ok": False,
            "errors": [f"Script not found: {script_path}"],
        }

    command = [
        "powershell.exe",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-AppRoot",
        str(app_root),
        *args,
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=str(app_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            env={
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
                "GIT_ASKPASS": "echo",
            },
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "errors": [f"{script_name} timed out after {timeout} seconds."],
        }
    except Exception as exc:
        return {
            "ok": False,
            "errors": [f"Unable to start {script_name}: {exc}"],
        }

    output = (completed.stdout or "").strip()
    error_output = (completed.stderr or "").strip()

    if completed.returncode != 0:
        return {
            "ok": False,
            "errors": [
                f"{script_name} exited with code {completed.returncode}.",
                error_output,
                output,
            ],
        }

    try:
        return _load_json_text(output)
    except Exception:
        return {
            "ok": False,
            "errors": [
                f"{script_name} completed but did not return valid JSON.",
                error_output,
                output,
            ],
        }


def generate_backup(reason: str = "manual", include_app_snapshot: bool = False):
    safe_reason = (reason or "manual").strip()[:80] or "manual"

    args = [
        "-BackupRoot",
        str(get_backup_root()),
        "-Reason",
        safe_reason,
    ]

    if include_app_snapshot:
        args.append("-IncludeAppSnapshot")

    result = _run_powershell_script(
        "production_backup.ps1",
        args=args,
        timeout=900,
    )

    if result.get("ok"):
        upsert_backup_metadata(result)

    return result


def import_existing_backups(limit: int = 100):
    archive_root = get_backup_root() / "archive"
    imported = 0
    errors = []

    if not archive_root.exists():
        return {
            "ok": True,
            "imported": 0,
            "errors": [],
        }

    for backup_dir in sorted(archive_root.iterdir(), reverse=True)[:limit]:
        if not backup_dir.is_dir():
            continue

        metadata_path = backup_dir / "metadata.json"

        if not metadata_path.exists():
            continue

        try:
            metadata = _load_json_file(metadata_path)
            upsert_backup_metadata(metadata)
            imported += 1
        except Exception as exc:
            errors.append(f"{backup_dir.name}: {exc}")

    return {
        "ok": len(errors) == 0,
        "imported": imported,
        "errors": errors,
    }


def get_update_status():
    current_manifest_path = get_app_root() / "release_manifest.json"

    current_manifest = {}
    if current_manifest_path.exists():
        try:
            current_manifest = _load_json_file(current_manifest_path)
        except Exception:
            current_manifest = {}

    try:
        request = Request(
            PUBLIC_RELEASE_MANIFEST_URL,
            headers={"User-Agent": "Launchpad-Update-Checker"},
        )

        with urlopen(request, timeout=20) as response:
            remote_manifest = json.loads(response.read().decode("utf-8-sig"))

        current_version = str(current_manifest.get("version") or "unknown")
        remote_version = str(remote_manifest.get("version") or "unknown")

        return {
            "ok": True,
            "source": "public_manifest",
            "current_version": current_version,
            "remote_version": remote_version,
            "update_available": current_version != remote_version,
            "working_tree_dirty": False,
            "release_manifest": remote_manifest,
            "release_notes_url": remote_manifest.get("release_notes_url"),
            "protected_files_changed": [],
            "errors": [],
        }

    except Exception as exc:
        return {
            "ok": False,
            "source": "public_manifest",
            "current_version": str(current_manifest.get("version") or "unknown"),
            "remote_version": "unknown",
            "update_available": False,
            "working_tree_dirty": False,
            "release_manifest": None,
            "release_notes_url": None,
            "protected_files_changed": [],
            "errors": [str(exc)],
        }


def apply_update():
    result = _run_powershell_script(
        "production_update.ps1",
        args=[
            "-BackupRoot",
            str(get_backup_root()),
            "-Apply",
        ],
        timeout=1800,
    )

    backup = result.get("backup")
    if isinstance(backup, dict) and backup.get("ok"):
        upsert_backup_metadata(backup)

    return result