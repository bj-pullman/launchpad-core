from google.oauth2 import service_account
from googleapiclient.discovery import build


DIRECTORY_SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
]


def build_directory_service(service_account_file: str, delegated_admin: str):
    credentials = service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=DIRECTORY_SCOPES,
    )

    delegated_credentials = credentials.with_subject(delegated_admin)

    return build(
        "admin",
        "directory_v1",
        credentials=delegated_credentials,
        cache_discovery=False,
    )


def is_member_of_group(service, group_email: str, user_email: str) -> bool:
    result = (
        service.members()
        .hasMember(groupKey=group_email, memberKey=user_email)
        .execute()
    )

    return bool(result.get("isMember", False))


def is_user_in_allowed_groups(
    service,
    user_email: str,
    required_groups: list[str],
    match_mode: str = "any",
) -> bool:
    if not required_groups:
        return False

    checks = [
        is_member_of_group(service, group_email, user_email)
        for group_email in required_groups
    ]

    if match_mode == "all":
        return all(checks)

    return any(checks)