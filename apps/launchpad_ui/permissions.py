from flask import session


SETTINGS_SECTIONS = [
    {
        "key": "general",
        "label": "General",
        "endpoint": "launchpad_ui.settings_general",
        "permission": "launchpad.settings.general.view",
    },
    {
        "key": "snipeops",
        "label": "SnipeOps",
        "endpoint": "launchpad_ui.settings_snipeops",
        "permission": "launchpad.settings.snipeops.view",
    },
    {
        "key": "authentication",
        "label": "Authentication",
        "endpoint": "launchpad_ui.settings_authentication",
        # keep existing permission key for compatibility
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
]


def get_visible_settings_sections():
    user_permissions = set(session.get("user_permissions", []))
    return [
        section
        for section in SETTINGS_SECTIONS
        if section["permission"] in user_permissions
    ]


def get_visible_launchpad_apps():
    user_permissions = set(session.get("user_permissions", []))
    return [
        app
        for app in LAUNCHPAD_APPS
        if app["permission"] in user_permissions
    ]