from apps.snipeops.snipe_catalog.sync import run_full_sync


def run_snipe_catalog_sync():
    """
    Refresh Launchpad's local Snipe Catalog cache from Snipe-IT.
    """
    result = run_full_sync()

    if not result.get("ok"):
        error = (
            result.get("error")
            or result.get("message")
            or "Snipe Catalog synchronization failed."
        )

        print(
            f"[snipe-sync] failed: {error}; "
            f"partial_counts={result.get('counts') or {}}",
            flush=True,
        )

        raise RuntimeError(error)

    print(
        "[snipe-sync] successful; "
        f"last_sync_utc={result.get('last_sync_utc')}; "
        f"counts={result.get('counts') or {}}",
        flush=True,
    )

    return result


def get_snipe_catalog_sync_jobs():
    return [
        {
            "job_id": "snipe.catalog_sync",
            "enabled_setting": "snipeops.catalog_sync.enabled",
            "enabled_default": True,
            "schedule_type": "interval_minutes",
            "interval_setting": "snipeops.catalog_sync.interval_minutes",
            "interval_default": 60,
            "func": run_snipe_catalog_sync,
        }
    ]