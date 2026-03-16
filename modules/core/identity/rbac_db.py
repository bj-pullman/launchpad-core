from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parents[3]

RBAC_DIR = BASE_DIR / "instance" / "rbac"
DATA_DIR = RBAC_DIR / "data"
RBAC_DB_PATH = DATA_DIR / "rbac.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(RBAC_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def init_rbac_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_key TEXT NOT NULL UNIQUE,
                role_name TEXT NOT NULL,
                description TEXT NULL,
                is_system INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                permission_key TEXT NOT NULL UNIQUE,
                permission_name TEXT NOT NULL,
                description TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS role_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_id INTEGER NOT NULL,
                permission_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(role_id, permission_id)
            );

            CREATE TABLE IF NOT EXISTS user_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS user_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                permission_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, permission_id)
            );

            CREATE INDEX IF NOT EXISTS idx_roles_role_key
            ON roles(role_key);

            CREATE INDEX IF NOT EXISTS idx_permissions_permission_key
            ON permissions(permission_key);

            CREATE INDEX IF NOT EXISTS idx_role_permissions_role_id
            ON role_permissions(role_id);

            CREATE INDEX IF NOT EXISTS idx_role_permissions_permission_id
            ON role_permissions(permission_id);

            CREATE INDEX IF NOT EXISTS idx_user_roles_user_id
            ON user_roles(user_id);

            CREATE INDEX IF NOT EXISTS idx_user_roles_role_id
            ON user_roles(role_id);

            CREATE INDEX IF NOT EXISTS idx_user_permissions_user_id
            ON user_permissions(user_id);

            CREATE INDEX IF NOT EXISTS idx_user_permissions_permission_id
            ON user_permissions(permission_id);
            """
        )

        # Safe migration support for older DBs
        if not _table_exists(conn, "user_permissions"):
            conn.execute(
                """
                CREATE TABLE user_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    permission_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, permission_id)
                )
                """
            )

        if not _column_exists(conn, "roles", "is_system"):
            conn.execute(
                """
                ALTER TABLE roles
                ADD COLUMN is_system INTEGER NOT NULL DEFAULT 0
                """
            )

        conn.commit()