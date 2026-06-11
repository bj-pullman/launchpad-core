from modules.core.integrations.entra_roster_sync import sync_entra_users_to_launchpad


def run_entra_user_sync():
    sync_entra_users_to_launchpad(trigger_type="scheduled")


def get_entra_user_sync_jobs():
    return [
        {
            "job_id": "entra.user_sync",
            "enabled_setting": "entra.user_sync.schedule_enabled",
            "schedule_type": "multi_hour",
            "hours_setting": "entra.user_sync.schedule_hours",
            "timezone_setting": "general.timezone",
            "func": run_entra_user_sync,
        }
    ]