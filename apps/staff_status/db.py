from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parents[3]
STAFF_STATUS_DIR = BASE_DIR / "instance" / "staff_status"
DATA_DIR = STAFF_STATUS_DIR / "data"
DB_PATH = DATA_DIR / "staff_status.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_staff_status_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS staff_status_departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_name TEXT NOT NULL UNIQUE,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                home_location_label TEXT NULL,
                kiosk_enabled INTEGER NOT NULL DEFAULT 0,
                kiosk_token TEXT NULL UNIQUE,
                kiosk_token_created_at TEXT NULL,
                kiosk_token_rotated_at TEXT NULL,
                board_enabled INTEGER NOT NULL DEFAULT 1,
                board_token TEXT NULL UNIQUE,
                board_token_created_at TEXT NULL,
                board_token_rotated_at TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS staff_status_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_name TEXT NOT NULL,
                location_label TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(department_name, location_label)
            );

            CREATE TABLE IF NOT EXISTS staff_status_current (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                department_name TEXT NOT NULL,
                location_labels_json TEXT NOT NULL,
                display_status_label TEXT NOT NULL,
                is_out_of_office INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                updated_by_user_id INTEGER NULL,
                updated_by_display_name TEXT NULL,
                updated_by_source TEXT NOT NULL DEFAULT 'user'
            );

            CREATE TABLE IF NOT EXISTS staff_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                department_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                location_labels_json TEXT NULL,
                private_status_type TEXT NULL,
                public_status_label TEXT NOT NULL,
                committed_by_user_id INTEGER NULL,
                committed_by_display_name TEXT NULL,
                committed_at TEXT NOT NULL,
                source_ip TEXT NULL,
                source_device TEXT NULL
            );

            CREATE TABLE IF NOT EXISTS staff_status_absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                department_name TEXT NOT NULL,
                absence_type TEXT NOT NULL,
                public_status_label TEXT NOT NULL DEFAULT 'Out of Office',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                note TEXT NULL,
                created_by_user_id INTEGER NOT NULL,
                created_by_display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_by_user_id INTEGER NULL,
                updated_by_display_name TEXT NULL,
                updated_at TEXT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_staff_status_departments_enabled
            ON staff_status_departments(is_enabled, department_name);

            CREATE INDEX IF NOT EXISTS idx_staff_status_locations_department
            ON staff_status_locations(department_name, is_active, sort_order, location_label);

            CREATE INDEX IF NOT EXISTS idx_staff_status_current_department
            ON staff_status_current(department_name, updated_at);

            CREATE INDEX IF NOT EXISTS idx_staff_status_history_user
            ON staff_status_history(user_id, committed_at);

            CREATE INDEX IF NOT EXISTS idx_staff_status_absences_lookup
            ON staff_status_absences(user_id, department_name, start_date, end_date, is_active);
            """
        )
        
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(staff_status_departments)").fetchall()]
        if "board_token" not in columns:
            conn.execute("ALTER TABLE staff_status_departments ADD COLUMN board_token TEXT NULL")
        if "board_token_created_at" not in columns:
            conn.execute("ALTER TABLE staff_status_departments ADD COLUMN board_token_created_at TEXT NULL")
        if "board_token_rotated_at" not in columns:
            conn.execute("ALTER TABLE staff_status_departments ADD COLUMN board_token_rotated_at TEXT NULL")

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_staff_status_departments_board_token
            ON staff_status_departments(board_token)
            WHERE board_token IS NOT NULL
            """
        )
        conn.commit()
