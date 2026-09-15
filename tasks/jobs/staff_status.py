from apps.staff_status.google_absence_sync import sync_google_absence_requests
from apps.staff_status.service import reset_all_enabled_departments


def get_staff_status_jobs():
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
            "interval_setting": "staff_status.absence_google_sync.interval_minutes",
            "interval_default": 5,
            "schedule_type": "interval_minutes",
        },
    ]
