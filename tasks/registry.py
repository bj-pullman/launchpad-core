from tasks.jobs.staff_status import get_staff_status_jobs
from tasks.jobs.entra_user_sync import get_entra_user_sync_jobs
from tasks.jobs.snipe_catalog_sync import get_snipe_catalog_sync_jobs


def get_all_jobs():
    jobs = []

    jobs.extend(get_staff_status_jobs())
    jobs.extend(get_entra_user_sync_jobs())
    jobs.extend(get_snipe_catalog_sync_jobs())

    return jobs