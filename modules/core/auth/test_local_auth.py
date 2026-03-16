from modules.core.identity.user_service import upsert_user
from modules.core.auth.local_auth_service import (
    create_local_auth_account,
    verify_local_login,
)

user = upsert_user(
    {
        "source_type": "manual",
        "source_id": "admin-local-001",
        "email": "admin@sheridanschools.org",
        "username": "admin",
        "display_name": "Local Admin",
        "first_name": "Local",
        "last_name": "Admin",
        "is_active": 1,
    }
)

account = create_local_auth_account(
    user_id=user["id"],
    username="admin",
    password="ChangeMeNow123!",
    is_active=1,
    is_breakglass=1,
)

print("ACCOUNT:", account)
print("VERIFY:", verify_local_login("admin", "ChangeMeNow123!"))