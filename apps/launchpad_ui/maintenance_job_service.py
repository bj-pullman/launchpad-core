import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path


JOB_ROOT = Path(__file__).resolve().parents[2] / "instance" / "maintenance" / "jobs"
UPDATE_STATUS_PATH = Path(__file__).resolve().parents[2] / "instance" / "maintenance" / "update_status.json"


def _utc_now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _ensure_dirs():
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    UPDATE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)


def _job_path(job_id: str) -> Path:
    return JOB_ROOT / f"{job_id}.json"


def write_json(path: Path, payload: dict):
    _ensure_dirs()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(path)


def read_json(path: Path, default=None):
    if default is None:
        default = None

    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def create_job(job_type: str):
    _ensure_dirs()

    job_id = uuid.uuid4().hex

    job = {
        "id": job_id,
        "type": job_type,
        "status": "queued",
        "created_at": _utc_now(),
        "started_at": None,
        "finished_at": None,
        "message": "Queued.",
        "result": None,
        "errors": [],
    }

    write_json(_job_path(job_id), job)
    return job


def get_job(job_id: str):
    if not job_id:
        return None

    return read_json(_job_path(job_id), None)


def get_latest_job(job_type: str):
    _ensure_dirs()

    jobs = []

    for path in JOB_ROOT.glob("*.json"):
        job = read_json(path, None)
        if not job:
            continue

        if job.get("type") == job_type:
            jobs.append(job)

    if not jobs:
        return None

    jobs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return jobs[0]


def get_cached_update_status():
    return read_json(UPDATE_STATUS_PATH, None)


def start_update_check_job():
    job = create_job("check_update")

    command = [
        sys.executable,
        "-m",
        "apps.launchpad_ui.maintenance_worker",
        "--job-id",
        job["id"],
        "--job-type",
        "check_update",
    ]

    kwargs = {
        "cwd": str(Path(__file__).resolve().parents[2]),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": False,
    }

    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )

    subprocess.Popen(command, **kwargs)

    return job
    
def start_apply_update_job():
    job = create_job("apply_update")

    command = [
        sys.executable,
        "-m",
        "apps.launchpad_ui.maintenance_worker",
        "--job-id",
        job["id"],
        "--job-type",
        "apply_update",
    ]

    kwargs = {
        "cwd": str(Path(__file__).resolve().parents[2]),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": False,
    }

    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )

    subprocess.Popen(command, **kwargs)

    return job