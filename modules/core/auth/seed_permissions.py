from modules.core.identity.rbac_service import (
    create_role,
    create_permission,
    assign_permission_to_role,
)


def seed_permissions():
    # Roles
    create_role("super_admin", "Super Admin", "Full platform access", is_system=1)
    create_role("launchpad_admin", "Launchpad Admin", "Launchpad administration", is_system=1)
    create_role("snipeops_user", "SnipeOps User", "SnipeOps feature access", is_system=1)
    create_role("viewer", "Viewer", "Basic Launchpad access only", is_system=1)
    create_role("staff_status_admin", "Staff Status Admin", "Full Staff Status administration", is_system=1)

    create_role("finance_viewer", "Finance Viewer", "Finance read-only access", is_system=1)
    create_role("finance_operator", "Finance Operator", "Finance records and operations access", is_system=1)
    create_role("finance_admin", "Finance Admin", "Finance administration access", is_system=1)
    create_role("finance_budget_viewer", "Finance Budget Viewer", "Finance budget read-only access", is_system=1)
    create_role("finance_budget_operator", "Finance Budget Operator", "Finance budget operations access", is_system=1)
    create_role("finance_budget_admin", "Finance Budget Admin", "Finance full budget administration", is_system=1)

    # Permissions
    permission_keys = [
        # Launchpad home
        ("launchpad.home.view", "Launchpad Home"),
        ("launchpad.home.manage", "Manage Launchpad Home"),

        # Launchpad settings root
        ("launchpad.settings.view", "Launchpad Settings"),
        ("launchpad.settings.manage", "Manage Launchpad Settings"),

        # General settings
        ("launchpad.settings.general.view", "General Settings"),
        ("launchpad.settings.general.manage", "Manage General Settings"),

        # SnipeOps settings
        ("launchpad.settings.snipeops.view", "SnipeOps Settings"),
        ("launchpad.settings.snipeops.manage", "Manage SnipeOps Settings"),

        # SAML settings
        ("launchpad.settings.saml.view", "SAML Settings"),
        ("launchpad.settings.saml.manage", "Manage SAML Settings"),

        # Security settings
        ("launchpad.settings.security.view", "Security Settings"),
        ("launchpad.settings.security.manage", "Manage Security Settings"),

        # Groups settings
        ("launchpad.settings.groups.view", "Groups Settings"),
        ("launchpad.settings.groups.manage", "Manage Groups Settings"),

        # Users settings
        ("launchpad.settings.users.view", "Users Settings"),
        ("launchpad.settings.users.manage", "Manage Users Settings"),

        # Staff Status settings
        ("launchpad.settings.staff_status.view", "Staff Status Settings"),
        ("launchpad.settings.staff_status.manage", "Manage Staff Status Settings"),

        # Finance settings
        ("launchpad.settings.finance.view", "Finance Settings View"),
        ("launchpad.settings.finance.operator", "Finance Settings Operator"),
        ("launchpad.settings.finance.admin", "Finance Settings Admin"),

        # SnipeOps app access
        ("snipeops.home.view", "SnipeOps Home"),
        ("snipeops.home.manage", "Manage SnipeOps Home"),
        ("snipeops.import_by_scan.view", "Import by Scan"),
        ("snipeops.import_by_scan.manage", "Manage Import by Scan"),
        ("snipeops.snipe_catalog.view", "Snipe Catalog"),
        ("snipeops.snipe_catalog.manage", "Manage Snipe Catalog"),

        # Staff Status app access
        ("staff_status.app.view", "Staff Status App View"),
        ("staff_status.view", "Staff Status View"),
        ("staff_status.operator", "Staff Status Operator"),
        ("staff_status.admin", "Staff Status Admin"),

        # Finance app access
        ("finance.home.view", "Finance Home"),

        ("finance.view", "Finance View"),
        ("finance.operator", "Finance Operator"),
        ("finance.admin", "Finance Admin"),

        ("finance.records.view", "Finance Records View"),
        ("finance.records.operator", "Finance Records Operator"),
        ("finance.records.admin", "Finance Records Admin"),

        ("finance.vendors.view", "Finance Vendors View"),
        ("finance.vendors.operator", "Finance Vendors Operator"),
        ("finance.vendors.admin", "Finance Vendors Admin"),

        ("finance.imports.view", "Finance Imports View"),
        ("finance.imports.operator", "Finance Imports Operator"),
        ("finance.imports.admin", "Finance Imports Admin"),

        ("finance.reports.view", "Finance Reports View"),
        ("finance.reports.operator", "Finance Reports Operator"),
        ("finance.reports.admin", "Finance Reports Admin"),

        ("finance.budget.view", "Finance Budget View"),
        ("finance.budget.operator", "Finance Budget Operator"),
        ("finance.budget.admin", "Finance Budget Admin"),

        # Future apps
        ("user360.home.view", "User360 Home"),
        ("user360.home.manage", "Manage User360 Home"),

        ("gam.home.view", "GAM Home"),
        ("gam.home.manage", "Manage GAM Home"),

        ("newhire.home.view", "New Hire Intake Home"),
        ("newhire.home.manage", "Manage New Hire Intake Home"),

        ("virtual_students.home.view", "Virtual Student Tracker Home"),
        ("virtual_students.home.manage", "Manage Virtual Student Tracker Home"),

        ("techhub.home.view", "Tech Hub Home"),
        ("techhub.home.manage", "Manage Tech Hub Home"),
    ]

    for key, name in permission_keys:
        create_permission(key, name)

    # Super Admin gets everything
    for key, _ in permission_keys:
        assign_permission_to_role("super_admin", key)

    # Viewer gets basic platform access only
    assign_permission_to_role("viewer", "launchpad.home.view")

    # Launchpad Admin
    launchpad_admin_permissions = [
        "launchpad.home.view",
        "launchpad.settings.view",
        "launchpad.settings.manage",

        "launchpad.settings.general.view",
        "launchpad.settings.general.manage",

        "launchpad.settings.snipeops.view",
        "launchpad.settings.snipeops.manage",

        "launchpad.settings.saml.view",
        "launchpad.settings.saml.manage",

        "launchpad.settings.security.view",
        "launchpad.settings.security.manage",

        "launchpad.settings.groups.view",
        "launchpad.settings.groups.manage",

        "launchpad.settings.users.view",
        "launchpad.settings.users.manage",

        "launchpad.settings.staff_status.view",
        "launchpad.settings.staff_status.manage",

        "launchpad.settings.finance.view",
        "launchpad.settings.finance.operator",
        "launchpad.settings.finance.admin",
    ]

    for key in launchpad_admin_permissions:
        assign_permission_to_role("launchpad_admin", key)

    # SnipeOps User
    snipeops_user_permissions = [
        "launchpad.home.view",
        "snipeops.home.view",
        "snipeops.import_by_scan.view",
        "snipeops.snipe_catalog.view",
    ]

    for key in snipeops_user_permissions:
        assign_permission_to_role("snipeops_user", key)

    # Staff Status Admin
    staff_status_admin_permissions = [
        "launchpad.home.view",
        "staff_status.app.view",
        "staff_status.view",
        "staff_status.operator",
        "staff_status.admin",
    ]

    for key in staff_status_admin_permissions:
        assign_permission_to_role("staff_status_admin", key)

    # Finance Viewer
    finance_viewer_permissions = [
        "launchpad.home.view",
        "finance.home.view",
        "finance.view",
        "finance.records.view",
        "finance.vendors.view",
        "finance.imports.view",
        "finance.reports.view",
    ]

    for key in finance_viewer_permissions:
        assign_permission_to_role("finance_viewer", key)

    # Finance Operator
    finance_operator_permissions = [
        "launchpad.home.view",
        "finance.home.view",
        "finance.view",
        "finance.operator",
        "finance.records.view",
        "finance.records.operator",
        "finance.vendors.view",
        "finance.vendors.operator",
        "finance.imports.view",
        "finance.imports.operator",
        "finance.reports.view",
        "finance.reports.operator",
        "launchpad.settings.finance.view",
    ]

    for key in finance_operator_permissions:
        assign_permission_to_role("finance_operator", key)

    # Finance Admin
    finance_admin_permissions = [
        "launchpad.home.view",
        "finance.home.view",
        "finance.view",
        "finance.operator",
        "finance.admin",
        "finance.records.view",
        "finance.records.operator",
        "finance.records.admin",
        "finance.vendors.view",
        "finance.vendors.operator",
        "finance.vendors.admin",
        "finance.imports.view",
        "finance.imports.operator",
        "finance.imports.admin",
        "finance.reports.view",
        "finance.reports.operator",
        "finance.reports.admin",
        "launchpad.settings.finance.view",
        "launchpad.settings.finance.operator",
        "launchpad.settings.finance.admin",
    ]

    for key in finance_admin_permissions:
        assign_permission_to_role("finance_admin", key)

    # Finance Budget Viewer
    finance_budget_viewer_permissions = [
        "launchpad.home.view",
        "finance.home.view",
        "finance.budget.view",
    ]

    for key in finance_budget_viewer_permissions:
        assign_permission_to_role("finance_budget_viewer", key)

    # Finance Budget Operator
    finance_budget_operator_permissions = [
        "launchpad.home.view",
        "finance.home.view",
        "finance.budget.view",
        "finance.budget.operator",
    ]

    for key in finance_budget_operator_permissions:
        assign_permission_to_role("finance_budget_operator", key)

    # Finance Budget Admin
    finance_budget_admin_permissions = [
        "launchpad.home.view",
        "finance.home.view",
        "finance.budget.view",
        "finance.budget.operator",
        "finance.budget.admin",
    ]

    for key in finance_budget_admin_permissions:
        assign_permission_to_role("finance_budget_admin", key)