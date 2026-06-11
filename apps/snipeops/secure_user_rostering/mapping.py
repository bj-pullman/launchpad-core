DEFAULT_USER_FIELD_MAPPING = [
    {
        "launchpad_field": "first_name",
        "snipe_field": "first_name",
        "label": "First Name",
        "required": True,
    },
    {
        "launchpad_field": "last_name",
        "snipe_field": "last_name",
        "label": "Last Name",
        "required": True,
    },
    {
        "launchpad_field": "email",
        "snipe_field": "email",
        "label": "Email",
        "required": True,
    },
    {
        "launchpad_field": "username",
        "snipe_field": "username",
        "label": "Username",
        "required": False,
    },
    {
        "launchpad_field": "employee_id",
        "snipe_field": "employee_num",
        "label": "Employee Number",
        "required": False,
    },
    {
        "launchpad_field": "job_title",
        "snipe_field": "jobtitle",
        "label": "Job Title",
        "required": False,
    },
    {
        "launchpad_field": "department",
        "snipe_field": "department",
        "label": "Department",
        "required": False,
    },
    {
        "launchpad_field": "office_location",
        "snipe_field": "location",
        "label": "Location",
        "required": False,
    },
]


def get_default_user_field_mapping():
    return DEFAULT_USER_FIELD_MAPPING