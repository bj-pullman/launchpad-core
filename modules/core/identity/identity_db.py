from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parents[3]

IDENTITY_DIR = BASE_DIR / "instance" / "identity"
DATA_DIR = IDENTITY_DIR / "data"

IDENTITY_DB_PATH = DATA_DIR / "identity.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(IDENTITY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_user_absence_allowance_columns():
    allowance_columns = {
        "sick_allowance_days": "REAL DEFAULT 12",
        "personal_allowance_days": "REAL DEFAULT 3",
        "vacation_allowance_days": "REAL DEFAULT 10",
        "other_allowance_days": "REAL DEFAULT 0",
    }

    with get_connection() as conn:
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }

        for column_name, column_type in allowance_columns.items():
            if column_name not in existing_columns:
                conn.execute(
                    f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                )

        conn.commit()

def ensure_user_theme_columns():
    with get_connection() as conn:
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }

        if "theme_preference" not in existing_columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN theme_preference TEXT NOT NULL DEFAULT 'light'"
            )

        conn.commit()


def init_identity_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            source_type TEXT NULL,
            source_id TEXT NULL,

            email TEXT NOT NULL UNIQUE,
            username TEXT NULL,
            display_name TEXT NULL,

            first_name TEXT NULL,
            last_name TEXT NULL,

            is_active INTEGER NOT NULL DEFAULT 1,

            job_title TEXT NULL,
            department TEXT NULL,
            office_location TEXT NULL,
            company_name TEXT NULL,
            employee_id TEXT NULL,
            preferred_language TEXT NULL,

            business_phone TEXT NULL,
            mobile_phone TEXT NULL,

            manager_source_id TEXT NULL,
            manager_email TEXT NULL,
            manager_display_name TEXT NULL,

            last_synced_at TEXT NULL,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_users_email
        ON users(email);

        CREATE INDEX IF NOT EXISTS idx_users_source
        ON users(source_type, source_id);
        """)

        ensure_user_absence_allowance_columns()
        ensure_user_theme_columns()
        
        conn.commit()