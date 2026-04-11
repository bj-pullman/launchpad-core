from datetime import datetime, timezone

from modules.core.auth.local_auth_db import get_connection
from modules.core.auth.passwords import hash_password, verify_password

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_username(username: str | None) -> str | None:
    if not username:
        return None
    value = username.strip().lower()
    return value or None


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def get_local_auth_by_username(username: str):
    normalized = normalize_username(username)
    if not normalized:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM local_auth_accounts
            WHERE username = ?
            """,
            (normalized,),
        ).fetchone()

    return row_to_dict(row)


def create_local_auth_account(
    user_id: int,
    username: str,
    password: str | None = None,
    password_hash: str | None = None,
    is_active: int = 1,
    is_breakglass: int = 0,
):
    normalized_username = normalize_username(username)
    if not normalized_username:
        raise ValueError("username is required")

    if password_hash is None and password is not None:
        password_hash = hash_password(password)

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO local_auth_accounts (
                user_id,
                username,
                password_hash,
                is_active,
                is_breakglass,
                last_login_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                user_id,
                normalized_username,
                password_hash,
                int(is_active),
                int(is_breakglass),
                now,
                now,
            ),
        )
        conn.commit()

    return get_local_auth_by_username(normalized_username)


def verify_local_login(username: str, password: str):
    from modules.core.identity.user_service import get_user_by_id
    
    account = get_local_auth_by_username(username)
    if not account:
        return None

    if not account.get("is_active", 0):
        return None

    if not verify_password(password, account["password_hash"]):
        return None

    user = get_user_by_id(account["user_id"])
    if not user:
        return None

    if not user.get("is_active", 0):
        return None

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE local_auth_accounts
            SET last_login_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (utc_now_iso(), utc_now_iso(), account["id"]),
        )
        conn.commit()

    return {
        "auth_account": account,
        "user": user,
    }

def set_local_password(username: str, password: str):
    account = get_local_auth_by_username(username)
    if not account:
        raise ValueError("local auth account not found")

    new_hash = hash_password(password)
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE local_auth_accounts
            SET password_hash = ?, updated_at = ?
            WHERE username = ?
            """,
            (new_hash, now, normalize_username(username)),
        )
        conn.commit()

    return get_local_auth_by_username(username)

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