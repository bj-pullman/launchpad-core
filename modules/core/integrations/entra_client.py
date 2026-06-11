import requests

from modules.core.settings.settings_service import get_setting


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class EntraClientError(Exception):
    pass


def get_graph_token() -> str:
    tenant_id = (get_setting("entra.tenant_id", "") or "").strip()
    client_id = (get_setting("entra.client_id", "") or "").strip()
    client_secret = (get_setting("entra.client_secret", "") or "").strip()

    if not tenant_id or not client_id or not client_secret:
        raise EntraClientError("Entra tenant ID, client ID, and client secret are required.")

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    response = requests.post(
        url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )

    if response.status_code >= 400:
        raise EntraClientError(f"Unable to get Microsoft Graph token: {response.text}")

    return response.json()["access_token"]


def list_entra_users() -> list[dict]:
    token = get_graph_token()
    group_id = (get_setting("entra.user_sync.group_id", "") or "").strip()

    if not group_id:
        raise EntraClientError("Target Entra Group Object ID is required for user sync.")

    select_fields = ",".join(
        [
            "id",
            "userPrincipalName",
            "mail",
            "displayName",
            "givenName",
            "surname",
            "jobTitle",
            "department",
            "officeLocation",
            "employeeId",
            "accountEnabled",
            "mobilePhone",
            "businessPhones",
            "preferredLanguage",
            "companyName",
        ]
    )

    url = (
        f"{GRAPH_BASE_URL}/groups/{group_id}/transitiveMembers/"
        f"microsoft.graph.user?$select={select_fields}&$top=999"
    )

    headers = {"Authorization": f"Bearer {token}"}
    users = []

    while url:
        response = requests.get(url, headers=headers, timeout=60)

        if response.status_code >= 400:
            raise EntraClientError(f"Unable to list Entra group users: {response.text}")

        payload = response.json()

        for user in payload.get("value", []):
            upn = (user.get("userPrincipalName") or "").strip().lower()
            mail = (user.get("mail") or "").strip().lower()
            display_name = (user.get("displayName") or "").strip().lower()

            if "#ext#" in upn:
                continue

            if upn.startswith("_template") or mail.startswith("_template") or display_name.startswith("_template"):
                continue

            users.append(user)

        url = payload.get("@odata.nextLink")

    return users