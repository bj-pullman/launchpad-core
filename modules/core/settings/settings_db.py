from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parents[3]

SETTINGS_DIR = BASE_DIR / "instance" / "settings"
DATA_DIR = SETTINGS_DIR / "data"
SETTINGS_DB_PATH = DATA_DIR / "settings.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(SETTINGS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_settings_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT NOT NULL UNIQUE,
                setting_value TEXT NULL,
                is_sensitive INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_app_settings_key
            ON app_settings(setting_key);
            """
        )
        conn.commit()