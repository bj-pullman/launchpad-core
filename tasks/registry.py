from tasks.jobs.staff_status import get_staff_status_jobs


def get_all_jobs():
    jobs = []
    jobs.extend(get_staff_status_jobs())
    return jobs