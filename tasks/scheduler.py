from datetime import datetime
import zoneinfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from flask import current_app, has_app_context

from modules.core.settings.settings_service import get_bool_setting, get_setting
from tasks.registry import get_all_jobs
from tasks.job_runs import (
    has_successful_run,
    init_job_runs_db,
    mark_job_failed,
    mark_job_finished,
    mark_job_started,
)

_scheduler = None
_application = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def start_scheduler():
    init_job_runs_db()

    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()

    return scheduler


def _parse_daily_time(value: str | None):
    try:
        hour_str, minute_str = (value or "01:00").split(":", 1)
        return int(hour_str), int(minute_str)
    except Exception:
        return 1, 0

def _parse_hour_list(value: str | None) -> list[int]:
    hours = []

    for item in (value or "6,14").split(","):
        item = item.strip()
        if not item:
            continue

        try:
            hour = int(item)
        except ValueError:
            continue

        if 0 <= hour <= 23 and hour not in hours:
            hours.append(hour)

    return hours or [6, 14]

def _parse_interval_minutes(
    value: str | int | None,
    default: int = 60,
    minimum: int = 5,
    maximum: int = 10080,
) -> int:
    """
    Parse and constrain a configurable scheduler interval.

    Minimum: 5 minutes
    Maximum: 10,080 minutes, or 7 days
    """
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = default

    return max(minimum, min(interval, maximum))

def _run_job_with_tracking(job_def):
    timezone_value = (
        get_setting(job_def["timezone_setting"], "America/Chicago")
        or "America/Chicago"
    )
    tz = zoneinfo.ZoneInfo(timezone_value)
    run_date = datetime.now(tz).date().isoformat()
    job_id = job_def["job_id"]

    if has_successful_run(job_id, run_date):
        print(f"[tasks] skipping {job_id}; already successful for {run_date}")
        return

    mark_job_started(job_id, run_date)

    try:
        print(f"[tasks] running {job_id} for {run_date}")
        if _application is not None:
            with _application.app_context():
                job_def["func"]()
        else:
            job_def["func"]()
        mark_job_finished(job_id, run_date)
        print(f"[tasks] completed {job_id} for {run_date}")
    except Exception as exc:
        mark_job_failed(job_id, run_date, str(exc))
        print(f"[tasks] failed {job_id}: {exc}")
        raise

def _run_interval_job_with_tracking(job_def):
    """
    Run an interval-based job and create a separate history record
    for every execution.

    Daily jobs use the date as their unique run key. Interval jobs
    need a timestamp so multiple executions can be recorded each day.
    """
    job_id = job_def["job_id"]

    run_key = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    mark_job_started(job_id, run_key)

    try:
        print(
            f"[tasks] running interval job {job_id} "
            f"for {run_key}",
            flush=True,
        )

        if _application is not None:
            with _application.app_context():
                result = job_def["func"]()
        else:
            result = job_def["func"]()

        mark_job_finished(job_id, run_key)

        if isinstance(result, dict):
            counts = result.get("counts") or {}
            last_sync = result.get("last_sync_utc")

            print(
                f"[tasks] completed interval job {job_id}; "
                f"run={run_key}; "
                f"last_sync_utc={last_sync or 'not provided'}; "
                f"counts={counts}",
                flush=True,
            )
        else:
            print(
                f"[tasks] completed interval job {job_id}; "
                f"run={run_key}",
                flush=True,
            )

        return result

    except Exception as exc:
        mark_job_failed(
            job_id,
            run_key,
            str(exc),
        )

        print(
            f"[tasks] failed interval job {job_id}; "
            f"run={run_key}; "
            f"error={exc}",
            flush=True,
        )

        raise


def run_due_daily_jobs_once():
    for job_def in get_all_jobs():
        if job_def.get("schedule_type") != "daily_time":
            continue

        enabled = get_bool_setting(
            job_def["enabled_setting"],
            job_def.get("enabled_default", False),
        )
        if not enabled:
            continue

        timezone_value = (
            get_setting(job_def["timezone_setting"], "America/Chicago")
            or "America/Chicago"
        )
        tz = zoneinfo.ZoneInfo(timezone_value)
        now = datetime.now(tz)

        default_time = job_def.get("time_default", "01:00")

        hour, minute = _parse_daily_time(
            get_setting(job_def["time_setting"], default_time)
        )

        scheduled_today = now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

        run_date = now.date().isoformat()

        if now >= scheduled_today and not has_successful_run(job_def["job_id"], run_date):
            print(f"[tasks] catch-up running {job_def['job_id']} for {run_date}")
            _run_job_with_tracking(job_def)


def configure_jobs():
    global _application
    if has_app_context():
        _application = current_app._get_current_object()

    scheduler = start_scheduler()
    desired_jobs = get_all_jobs()

    desired_job_ids = {job_def["job_id"] for job_def in desired_jobs}
    desired_job_ids.add("tasks.daily_catchup")

    existing_jobs = {job.id: job for job in scheduler.get_jobs()}

    for existing_job_id in list(existing_jobs.keys()):
        if existing_job_id not in desired_job_ids:
            scheduler.remove_job(existing_job_id)

    for job_def in desired_jobs:
        job_id = job_def["job_id"]

        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        enabled = get_bool_setting(
            job_def["enabled_setting"],
            job_def.get("enabled_default", False),
        )
        if not enabled:
            continue

        #
        # Daily scheduled jobs
        #
        if job_def.get("schedule_type") == "daily_time":
            default_time = job_def.get("time_default", "01:00")

            time_value = get_setting(
                job_def["time_setting"],
                default_time,
            ) or default_time

            timezone_value = (
                get_setting(
                    job_def["timezone_setting"],
                    "America/Chicago"
                )
                or "America/Chicago"
            )

            hour, minute = _parse_daily_time(time_value)

            print(
                f"[tasks] scheduling {job_id} "
                f"at {hour:02d}:{minute:02d} "
                f"{timezone_value}"
            )

            scheduler.add_job(
                _run_job_with_tracking,
                args=[job_def],
                trigger=CronTrigger(
                    hour=hour,
                    minute=minute,
                    timezone=timezone_value,
                ),
                id=job_id,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
            )

        #
        # Multi-hour scheduled jobs
        #
        elif job_def.get("schedule_type") == "multi_hour":
            hours_value = (
                get_setting(
                    job_def["hours_setting"],
                    "6,14"
                )
                or "6,14"
            )

            timezone_value = (
                get_setting(
                    job_def["timezone_setting"],
                    "America/Chicago"
                )
                or "America/Chicago"
            )

            hours = _parse_hour_list(hours_value)

            print(
                f"[tasks] scheduling {job_id} "
                f"at hours {hours} "
                f"{timezone_value}"
            )

            scheduler.add_job(
                job_def["func"],
                trigger=CronTrigger(
                    hour=",".join(str(hour) for hour in hours),
                    minute=0,
                    timezone=timezone_value,
                ),
                id=job_id,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
            )

        #
        # Recurring interval jobs
        #
        elif job_def.get("schedule_type") == "interval_minutes":
            interval_default = job_def.get("interval_default", 60)

            interval_value = get_setting(
                job_def["interval_setting"],
                str(interval_default),
            )

            interval_minutes = _parse_interval_minutes(
                interval_value,
                default=interval_default,
            )

            print(
                f"[tasks] scheduling {job_id} "
                f"every {interval_minutes} minute(s)"
            )

            scheduler.add_job(
                _run_interval_job_with_tracking,
                args=[job_def],
                trigger=IntervalTrigger(
                    minutes=interval_minutes,
                ),
                id=job_id,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
            )

    scheduler.add_job(
        run_due_daily_jobs_once,
        trigger=IntervalTrigger(minutes=5),
        id="tasks.daily_catchup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    run_due_daily_jobs_once()


def get_configured_jobs():
    scheduler = get_scheduler()
    jobs = []

    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        })

    return jobs
