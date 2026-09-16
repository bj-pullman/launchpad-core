from apps.staff_status.google_absence_sync import get_google_absence_sync_settings, sync_google_absence_requests
from apps.staff_status.service import reset_all_enabled_departments


def get_staff_status_jobs():
    # Reading settings performs the one-time minutes-to-seconds migration before
    # the scheduler looks up the new interval key during application startup.
    get_google_absence_sync_settings()
    return [
        {
            "job_id": "staff_status.daily_reset",
            "label": "Staff Status Daily Reset",
            "func": reset_all_enabled_departments,
            "enabled_setting": "staff_status.daily_reset_enabled",
            "time_setting": "staff_status.daily_reset_time",
            "timezone_setting": "general.timezone",
            "schedule_type": "daily_time",
        },
        {
            "job_id": "staff_status.google_absence_sync",
            "label": "Staff Status Google Absence Sync",
            "func": sync_google_absence_requests,
            "enabled_setting": "staff_status.absence_google_sync.enabled",
            "interval_setting": "staff_status.absence_google_sync.interval_seconds",
            "interval_default": 60,
            "interval_minimum": 30,
            "interval_maximum": 86400,
            "schedule_type": "interval_seconds",
        },
    ]
