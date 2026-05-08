from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parents[2]
SNIPEOPS_DIR = BASE_DIR / "instance" / "snipeops"
DATA_DIR = SNIPEOPS_DIR / "data"
DB_PATH = DATA_DIR / "snipeops.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_mapping_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS snipeops_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source TEXT NOT NULL DEFAULT 'any',
                field TEXT NOT NULL,
                raw_value TEXT NOT NULL,
                mapped_value TEXT NOT NULL,

                notes TEXT NULL,

                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                UNIQUE(source, field, raw_value)
            );

            CREATE INDEX IF NOT EXISTS idx_snipeops_mappings_lookup
            ON snipeops_mappings(source, field, raw_value);

            CREATE INDEX IF NOT EXISTS idx_snipeops_mappings_field
            ON snipeops_mappings(field);
            """
        )

        conn.commit()