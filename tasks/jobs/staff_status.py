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
        }
    ]