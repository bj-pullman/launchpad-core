from flask import session

from apps.staff_status.access_service import list_accessible_departments_for_user
from modules.core.settings.settings_service import get_setting, get_bool_setting


SETTINGS_SECTIONS = [
    {
        "key": "general",
        "label": "General",
        "endpoint": "launchpad_ui.settings_general",
        "permission": "launchpad.settings.general.view",
    },
    {
        "key": "integrations",
        "label": "Integrations",
        "endpoint": "launchpad_ui.settings_integrations",
        "permissions_any": [
            "launchpad.settings.saml.view",
            "launchpad.settings.snipeops.view",
        ],
    },
    {
        "key": "staff_status",
        "label": "Staff Status",
        "endpoint": "launchpad_ui.settings_staff_status",
        "permission": "launchpad.settings.staff_status.view",
    },
    {
        "key": "authentication",
        "label": "Authentication",
        "endpoint": "launchpad_ui.settings_authentication",
        "permission": "launchpad.settings.saml.view",
    },
    {
        "key": "security",
        "label": "Security",
        "endpoint": "launchpad_ui.settings_security",
        "permission": "launchpad.settings.security.view",
    },
    {
        "key": "groups",
        "label": "Groups",
        "endpoint": "launchpad_ui.settings_groups",
        "permission": "launchpad.settings.groups.view",
    },
    {
        "key": "users",
        "label": "Users",
        "endpoint": "launchpad_ui.settings_users",
        "permission": "launchpad.settings.users.view",
    },
]


LAUNCHPAD_APPS = [
    {
        "key": "snipeops",
        "label": "SnipeOps",
        "description": "Operations tools and inventory workflows.",
        "endpoint": "snipeops.index",
        "permission": "snipeops.home.view",
    },
    {
        "key": "finance",
        "label": "Finance",
        "description": "Budget, renewals, and purchasing.",
        "endpoint": "finance.index",
        "permission": "finance.home.view",
    },
    {
        "key": "user360",
        "label": "User360",
        "description": "Read-only user overview.",
        "endpoint": "user360.index",
        "permission": "user360.home.view",
    },
    {
        "key": "gam",
        "label": "Google Apps Manager (GAM)",
        "description": "Run approved GAM scripts locally through a secure web interface.",
        "endpoint": "gam.index",
        "permission": "gam.home.view",
    },
    {
        "key": "newhire",
        "label": "New Hire Intake",
        "description": "Manage new hire intake, account preparation, and workflow status.",
        "endpoint": "newhire.index",
        "permission": "newhire.home.view",
    },
    {
        "key": "virtual_students",
        "label": "Virtual Student Tracker",
        "description": "Manage virtual student intake, account status, device preparation, and support tracking.",
        "endpoint": "virtual_students.index",
        "permission": "virtual_students.home.view",
    },
    {
        "key": "techhub",
        "label": "Tech Hub",
        "description": "Staff resources, training, documentation, announcements, and support links.",
        "endpoint": "techhub.index",
        "permission": "techhub.home.view",
    },
    {
        "key": "staff_status",
        "label": "Staff Status",
        "description": "Real-time staff location and availability tracking.",
        "endpoint": "staff_status.index",
        "permission": "staff_status.app.view",
    },
]


def get_visible_settings_sections():
    user_permissions = set(session.get("user_permissions", []))
    visible_sections = []

    for section in SETTINGS_SECTIONS:
        permission = section.get("permission")
        permissions_any = section.get("permissions_any", [])

        if permission and permission in user_permissions:
            visible_sections.append(section)
            continue

        if permissions_any and any(p in user_permissions for p in permissions_any):
            visible_sections.append(section)

    return visible_sections


def get_visible_launchpad_apps():
    user_permissions = set(session.get("user_permissions", []))
    user_id = session.get("user_id")

    snipeops_enabled = get_bool_setting("snipeops.enabled", False)
    snipeops_base_url = (get_setting("snipeops.base_url", "") or "").strip()
    snipeops_api_token = (get_setting("snipeops.api_token", "") or "").strip()
    snipeops_configured = bool(snipeops_base_url and snipeops_api_token)
    snipeops_admin = "launchpad.settings.snipeops.manage" in user_permissions

    visible_apps = []

    for app in LAUNCHPAD_APPS:
        if app["key"] == "staff_status":
            if (
                app["permission"] in user_permissions
                or ("staff_status.operator" in user_permissions)
                or ("staff_status.admin" in user_permissions)
                or (user_id and len(list_accessible_departments_for_user(user_id)) > 0)
            ):
                visible_apps.append(app)
            continue

        if app["key"] == "snipeops":
            if app["permission"] in user_permissions and (
                snipeops_admin or (snipeops_enabled and snipeops_configured)
            ):
                visible_apps.append(app)
            continue

        if app["permission"] in user_permissions:
            visible_apps.append(app)

    return visible_apps