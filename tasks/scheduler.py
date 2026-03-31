from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from modules.core.settings.settings_service import get_bool_setting, get_setting
from tasks.registry import get_all_jobs

_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def start_scheduler():
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
    return scheduler


def configure_jobs():
    scheduler = start_scheduler()
    desired_jobs = get_all_jobs()

    desired_job_ids = {job_def["job_id"] for job_def in desired_jobs}
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

        schedule_type = job_def.get("schedule_type")

        if schedule_type == "daily_time":
            time_value = get_setting(job_def["time_setting"], "01:00") or "01:00"
            timezone_value = (
                get_setting(job_def["timezone_setting"], "America/Chicago")
                or "America/Chicago"
            )

            try:
                hour_str, minute_str = time_value.split(":", 1)
                hour = int(hour_str)
                minute = int(minute_str)
            except Exception:
                hour = 1
                minute = 0

            print(
                f"[tasks] scheduling {job_id} at {hour:02d}:{minute:02d} {timezone_value}"
            )
            
            scheduler.add_job(
                job_def["func"],
                    trigger=CronTrigger(
                        hour=hour,
                        minute=minute,
                        timezone=timezone_value,
                    ),
                id=job_id,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )


def get_configured_jobs():
    scheduler = get_scheduler()
    jobs = []

    for job in scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat()
                if job.next_run_time
                else None,
            }
        )

    return jobs