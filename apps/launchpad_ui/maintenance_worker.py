import argparse

from .backup_service import get_update_status, apply_update
from .maintenance_job_service import (
    UPDATE_STATUS_PATH,
    _job_path,
    _utc_now,
    read_json,
    write_json,
)


def _update_job(job_id: str, **updates):
    path = _job_path(job_id)
    job = read_json(path, {}) or {}
    job.update(updates)
    write_json(path, job)
    return job


def run_check_update(job_id: str):
    _update_job(
        job_id,
        status="running",
        started_at=_utc_now(),
        message="Checking for updates.",
    )

    try:
        result = get_update_status()

        status = "completed" if result.get("ok") else "failed"
        message = "Update check completed." if result.get("ok") else "Update check failed."

        write_json(UPDATE_STATUS_PATH, {
            "checked_at": _utc_now(),
            "result": result,
        })

        _update_job(
            job_id,
            status=status,
            finished_at=_utc_now(),
            message=message,
            result=result,
            errors=result.get("errors") or ([] if result.get("ok") else [result.get("error") or "Unknown error"]),
        )

    except Exception as exc:
        _update_job(
            job_id,
            status="failed",
            finished_at=_utc_now(),
            message="Update check failed.",
            result=None,
            errors=[str(exc)],
        )


def run_apply_update(job_id: str):
    _update_job(
        job_id,
        status="running",
        started_at=_utc_now(),
        message="Applying update.",
    )

    try:
        result = apply_update()

        status = "completed" if result.get("ok") else "failed"
        message = "Update applied." if result.get("ok") else "Update failed."

        _update_job(
            job_id,
            status=status,
            finished_at=_utc_now(),
            message=message,
            result=result,
            errors=result.get("errors") or ([] if result.get("ok") else [result.get("error") or "Unknown error"]),
        )

    except Exception as exc:
        _update_job(
            job_id,
            status="failed",
            finished_at=_utc_now(),
            message="Update failed.",
            result=None,
            errors=[str(exc)],
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--job-type", required=True)
    args = parser.parse_args()

    if args.job_type == "check_update":
        run_check_update(args.job_id)
        return

    if args.job_type == "apply_update":
        run_apply_update(args.job_id)
        return

    _update_job(
        args.job_id,
        status="failed",
        finished_at=_utc_now(),
        message=f"Unsupported job type: {args.job_type}",
        errors=[f"Unsupported job type: {args.job_type}"],
    )


if __name__ == "__main__":
    main()