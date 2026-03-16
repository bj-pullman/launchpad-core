from modules.core.identity.user_service import get_user_by_email, upsert_user
from modules.core.auth.local_auth_service import get_local_auth_by_username, create_local_auth_account
from modules.core.identity.rbac_service import assign_role_to_user, get_user_role_keys


ADMIN_EMAIL = "admin@local"
ADMIN_USERNAME = "admin"
ADMIN_DISPLAY_NAME = "Local Administrator"


def ensure_default_local_admin():
    user = get_user_by_email(ADMIN_EMAIL)

    if not user:
        user = upsert_user({
            "source_type": "manual",
            "source_id": "local-admin",
            "email": ADMIN_EMAIL,
            "username": ADMIN_USERNAME,
            "display_name": ADMIN_DISPLAY_NAME,
            "first_name": "Local",
            "last_name": "Administrator",
            "is_active": 1,
        })

    auth = get_local_auth_by_username(ADMIN_USERNAME)

    if not auth:
        create_local_auth_account(
            user_id=user["id"],
            username=ADMIN_USERNAME,
            password_hash=None,   # password not set yet
            is_active=1,
            is_breakglass=1
        )

    roles = get_user_role_keys(user["id"])

    if "super_admin" not in roles:
        assign_role_to_user(user["id"], "super_admin")