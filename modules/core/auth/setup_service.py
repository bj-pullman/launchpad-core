from modules.core.auth.local_auth_service import get_local_auth_by_username


def is_initial_setup_required():
    auth = get_local_auth_by_username("admin")

    if not auth:
        return True

    return not bool(auth.get("password_hash"))