from modules.core.settings.settings_db import get_connection


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def init_sync_tables():
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_key TEXT NOT NULL,
                source_system TEXT NOT NULL,
                target_system TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NULL,
                created_count INTEGER NOT NULL DEFAULT 0,
                updated_count INTEGER NOT NULL DEFAULT 0,
                unchanged_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                message TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sync_runs_sync_key
            ON sync_runs(sync_key);

            CREATE TABLE IF NOT EXISTS snipeit_user_merge_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                launchpad_user_id INTEGER NULL,
                snipeit_user_id INTEGER NULL,
                entra_object_id TEXT NULL,
                match_status TEXT NOT NULL,
                match_score INTEGER NOT NULL DEFAULT 0,
                match_reason TEXT NULL,
                proposed_action TEXT NOT NULL,
                approved_action TEXT NULL,
                reviewed_by_user_id INTEGER NULL,
                reviewed_at TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_snipeit_user_merge_candidates_launchpad_user_id
            ON snipeit_user_merge_candidates(launchpad_user_id);

            CREATE INDEX IF NOT EXISTS idx_snipeit_user_merge_candidates_snipeit_user_id
            ON snipeit_user_merge_candidates(snipeit_user_id);
            """
        )

        if not _column_exists(conn, "sync_runs", "unchanged_count"):
            conn.execute(
                """
                ALTER TABLE sync_runs
                ADD COLUMN unchanged_count INTEGER NOT NULL DEFAULT 0
                """
            )

        conn.commit()