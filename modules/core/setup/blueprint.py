from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from modules.core.auth.local_auth_service import (
    get_local_auth_by_username,
    create_local_auth_account,
    set_local_password,
)
from modules.core.auth.setup_service import is_initial_setup_required
from modules.core.auth.decorators import login_required
from modules.core.identity.user_service import get_user_by_email
from modules.core.settings.settings_service import get_setting, set_setting, get_bool_setting
from modules.core.utils.time import utc_now_iso

bp = Blueprint("setup", __name__, url_prefix="/setup")


SETUP_STEPS = [
    {
        "key": "organization",
        "label": "Organization",
        "title": "Organization Basics",
        "summary": "Configure the basic identity and public URL information Launchpad uses across the app.",
        "settings_later": "Settings → General",
        "skip_title": "Skip Organization Basics?",
        "skip_message": (
            "If you skip this step, Launchpad will still work, but generated links, "
            "kiosk URLs, password setup links, and displayed times may be incorrect "
            "until these settings are configured."
        ),
    },
    {
        "key": "email",
        "label": "Email",
        "title": "Email Integration",
        "summary": "Verify SMTP so Launchpad can send setup links, password reset links, notifications, and reminders.",
        "settings_later": "Settings → Integrations → Email",
        "skip_title": "Skip Email Integration?",
        "skip_message": (
            "If you skip this step, Launchpad cannot send account setup emails, "
            "password reset emails, Finance renewal reminders, or other system notifications "
            "until SMTP is configured."
        ),
    },
    {
        "key": "authentication",
        "label": "Authentication",
        "title": "Authentication",
        "summary": "Review how users will sign in using local auth, Google, Microsoft, SAML, or future identity integrations.",
        "settings_later": "Settings → Authentication",
        "skip_title": "Skip Authentication Setup?",
        "skip_message": (
            "If you skip this step, users will only be able to sign in using currently enabled "
            "methods. SSO and access-control rules can be configured later."
        ),
    },
    {
        "key": "users",
        "label": "Users",
        "title": "Users",
        "summary": "Review user creation, required CSV import fields, local account setup links, and user management workflow.",
        "settings_later": "Settings → Users",
        "skip_title": "Skip Users Setup?",
        "skip_message": (
            "If you skip this step, users must be created manually before they can sign in "
            "or appear in applications like Staff Status."
        ),
    },
    {
        "key": "apps",
        "label": "Apps",
        "title": "Applications",
        "summary": "Review readiness for Staff Status, Finance, SnipeOps, and other Launchpad applications.",
        "settings_later": "Settings",
        "skip_title": "Skip Application Readiness?",
        "skip_message": (
            "If you skip this step, some applications may be hidden, incomplete, or missing "
            "required integrations until configured later."
        ),
    },
    {
        "key": "review",
        "label": "Review",
        "title": "Review Setup",
        "summary": "Review completed and skipped setup areas before finishing the wizard.",
        "settings_later": "Settings → Setup",
        "skip_title": "",
        "skip_message": "",
    },
]


SETUP_STEP_KEYS = [step["key"] for step in SETUP_STEPS]


def _get_step(step_key: str):
    for step in SETUP_STEPS:
        if step["key"] == step_key:
            return step
    return None


def _next_step_key(step_key: str):
    try:
        index = SETUP_STEP_KEYS.index(step_key)
    except ValueError:
        return SETUP_STEP_KEYS[0]

    if index + 1 >= len(SETUP_STEP_KEYS):
        return "review"

    return SETUP_STEP_KEYS[index + 1]


def _mark_step_completed(step_key: str):
    set_setting(f"setup.{step_key}.completed", "1")
    set_setting(f"setup.{step_key}.skipped", "0")
    set_setting(f"setup.{step_key}.completed_at", utc_now_iso())


def _mark_step_skipped(step_key: str):
    set_setting(f"setup.{step_key}.completed", "0")
    set_setting(f"setup.{step_key}.skipped", "1")
    set_setting(f"setup.{step_key}.skipped_at", utc_now_iso())


def _wizard_status():
    status = {}

    for step in SETUP_STEPS:
        key = step["key"]

        if key == "review":
            continue

        status[key] = {
            "completed": get_bool_setting(f"setup.{key}.completed", False),
            "skipped": get_bool_setting(f"setup.{key}.skipped", False),
        }

    return status


def _wizard_context(step_key: str):
    step = _get_step(step_key) or SETUP_STEPS[0]

    return {
        "steps": SETUP_STEPS,
        "step": step,
        "step_key": step["key"],
        "status": _wizard_status(),
        "setup_completed": get_bool_setting("setup.completed", False),
        "organization_settings": {
            "organization_name": get_setting("general.organization_name", ""),
            "public_base_url": get_setting("general.public_base_url", ""),
            "timezone": get_setting("general.timezone", "America/Chicago"),
            "date_format": get_setting("general.date_format", "mdy"),
            "time_format": get_setting("general.time_format", "12h"),
        },
        "email_settings": {
            "smtp_configured": bool(
                get_setting("email.smtp_host", "")
                or get_setting("smtp.host", "")
                or get_setting("finance.notifications.sender_email", "")
            ),
        },
    }


@bp.route("/", methods=["GET", "POST"])
def initial_setup():
    if not is_initial_setup_required():
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = request.form.get("password")
        confirm = request.form.get("confirm")

        if not password or password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("setup/setup.html")

        admin_user = get_user_by_email("admin@local")
        if not admin_user:
            flash("Initial administrator account is missing.", "error")
            return render_template("setup/setup.html")

        admin_auth = get_local_auth_by_username("admin")
        if not admin_auth:
            create_local_auth_account(
                user_id=admin_user["id"],
                username="admin",
                password_hash=None,
                is_active=1,
                is_breakglass=1,
            )

        set_local_password("admin", password)

        set_setting("setup.local_admin.completed", "1")
        set_setting("setup.local_admin.completed_at", utc_now_iso())

        flash("Administrator password configured. Sign in to continue setup.", "success")
        return redirect(url_for("auth.login"))

    return render_template("setup/setup.html")


@bp.route("/wizard", methods=["GET"])
@login_required
def wizard_index():
    return redirect(url_for("setup.wizard_step", step_key="organization"))


@bp.route("/wizard/<step_key>", methods=["GET", "POST"])
@login_required
def wizard_step(step_key: str):
    step = _get_step(step_key)

    if not step:
        return redirect(url_for("setup.wizard_index"))

    if request.method == "POST":
        action = request.form.get("action", "save")

        if step_key == "review":
            set_setting("setup.completed", "1")
            set_setting("setup.completed_at", utc_now_iso())
            set_setting("setup.completed_by_user_id", str(session.get("user_id") or ""))
            flash("Setup wizard completed.", "success")
            return redirect(url_for("launchpad_ui.home"))

        if action == "skip":
            _mark_step_skipped(step_key)
            return redirect(url_for("setup.wizard_step", step_key=_next_step_key(step_key)))

        if step_key == "organization":
            organization_name = (request.form.get("organization_name") or "").strip()
            public_base_url = (request.form.get("public_base_url") or "").strip().rstrip("/")
            timezone_value = (request.form.get("timezone") or "America/Chicago").strip()
            date_format_value = (request.form.get("date_format") or "mdy").strip()
            time_format_value = (request.form.get("time_format") or "12h").strip()

            set_setting("general.organization_name", organization_name)
            set_setting("general.public_base_url", public_base_url)
            set_setting("general.timezone", timezone_value)
            set_setting("general.date_format", date_format_value)
            set_setting("general.time_format", time_format_value)

            _mark_step_completed(step_key)
            flash("Organization settings saved.", "success")

        else:
            _mark_step_completed(step_key)
            flash(f"{step['title']} marked complete.", "success")

        return redirect(url_for("setup.wizard_step", step_key=_next_step_key(step_key)))

    return render_template("setup/wizard.html", **_wizard_context(step_key))