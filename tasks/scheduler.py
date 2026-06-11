from datetime import datetime
import zoneinfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

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
        job_def["func"]()
        mark_job_finished(job_id, run_date)
        print(f"[tasks] completed {job_id} for {run_date}")
    except Exception as exc:
        mark_job_failed(job_id, run_date, str(exc))
        print(f"[tasks] failed {job_id}: {exc}")
        raise


def run_due_daily_jobs_once():
    for job_def in get_all_jobs():
        if job_def.get("schedule_type") != "daily_time":
            continue

        enabled = get_bool_setting(job_def["enabled_setting"], False)
        if not enabled:
            continue

        timezone_value = (
            get_setting(job_def["timezone_setting"], "America/Chicago")
            or "America/Chicago"
        )
        tz = zoneinfo.ZoneInfo(timezone_value)
        now = datetime.now(tz)

        hour, minute = _parse_daily_time(
            get_setting(job_def["time_setting"], "01:00")
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

        enabled = get_bool_setting(job_def["enabled_setting"], False)
        if not enabled:
            continue

        #
        # Daily scheduled jobs
        #
        if job_def.get("schedule_type") == "daily_time":
            time_value = get_setting(
                job_def["time_setting"],
                "01:00"
            ) or "01:00"

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