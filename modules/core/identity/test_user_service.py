from modules.core.identity.user_service import upsert_user, get_user_by_email

test_user = upsert_user(
    {
        "source_type": "manual",
        "source_id": "test-002",
        "email": "bjpullman@sheridanschools.org",
        "username": "bjpullman@sheridanschools.org",
        "display_name": "BJ Pullman Test",
        "first_name": "BJ",
        "last_name": "Pullman Test",
        "is_active": 1,
        "job_title": "Technology",
        "department": "Technology",
        "office_location": "Technology",
    }
)

print("UPSERTED:", test_user)
print("FETCHED:", get_user_by_email("bj.test@sheridanschools.org"))