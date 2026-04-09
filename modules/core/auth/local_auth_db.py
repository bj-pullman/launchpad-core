from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parents[3]

AUTH_DIR = BASE_DIR / "instance" / "auth"
DATA_DIR = AUTH_DIR / "data"
AUTH_DB_PATH = DATA_DIR / "auth.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_local_auth_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS local_auth_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_breakglass INTEGER NOT NULL DEFAULT 0,
                last_login_at TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_local_auth_user_id
            ON local_auth_accounts(user_id);

            CREATE INDEX IF NOT EXISTS idx_local_auth_username
            ON local_auth_accounts(username);

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
            """
        )
        conn.commit()

def delete_local_auth_account_by_user_id(user_id: int):
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM local_auth_accounts
            WHERE user_id = ?
            """,
            (user_id,),
        )
        conn.commit()