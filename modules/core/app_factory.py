import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, flash, redirect, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from apps.launchpad_ui import launchpad_ui_bp

from apps.snipeops.import_by_scan.blueprint import bp as import_by_scan_bp
from apps.snipeops.import_by_scan.import_by_scan_db import init_db as import_by_scan_init_db
from apps.snipeops.snipe_catalog.blueprint import bp as snipe_catalog_bp
from apps.snipeops.blueprint import bp as snipeops_bp
from apps.snipeops.mapping_db import init_mapping_db
from apps.snipeops.mapping_service import seed_default_mappings
from apps.snipeops.checkout_assets.blueprint import bp as checkout_assets_bp
from apps.snipeops.checkout_assets.checkout_assets_db import init_db as checkout_assets_init_db
from apps.snipeops.snipe_catalog.catalog_db import init_db as snipe_catalog_init_db
from apps.snipeops.media_catalog.blueprint import bp as media_catalog_bp
from apps.snipeops.media_catalog.media_catalog_db import init_db as media_catalog_init_db

from apps.staff_status.blueprint import bp as staff_status_bp
from apps.staff_status.db import init_staff_status_db
from apps.finance.blueprint import bp as finance_bp
from apps.finance.db import init_finance_db
from apps.finance.api_routes import finance_api_bp

from modules.core.auth.blueprint import bp as auth_bp
from modules.core.auth import routes as auth_routes  # noqa: F401
from modules.core.extensions import oauth

from modules.core.identity.identity_db import init_identity_db
from modules.core.auth.local_auth_db import init_local_auth_db
from modules.core.settings.settings_db import init_settings_db
from modules.core.auth.seed_permissions import seed_permissions
from modules.core.identity.rbac_db import init_rbac_db
from modules.core.auth.setup_service import is_initial_setup_required
from modules.core.setup.blueprint import bp as setup_bp
from modules.core.auth.bootstrap_admin import ensure_default_local_admin
from modules.core.utils.time import format_system_time, utc_now
from modules.core.settings.settings_service import get_setting, get_bool_setting
from modules.core.api_keys.service import init_api_keys_db
from modules.core.bootstrap.finance_seed import ensure_efinance_daily_import_profile
from modules.core.identity.user_service import get_user_by_id

from tasks.scheduler import configure_jobs
from tasks.job_runs import init_job_runs_db

load_dotenv()


def configure_logging():
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    def get_logging_timezone():
        try:
            return get_setting("general.timezone", "America/Chicago") or "America/Chicago"
        except Exception:
            return "America/Chicago"

    class TimezoneFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            tz_name = get_logging_timezone()

            try:
                tz = ZoneInfo(tz_name)
                dt = datetime.fromtimestamp(record.created, tz)
            except Exception:
                dt = datetime.fromtimestamp(record.created)

            if datefmt:
                return dt.strftime(datefmt)

            return dt.isoformat()

    formatter = TimezoneFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "%Y-%m-%d %H:%M:%S %Z",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    log_dir = os.getenv("LOG_DIR") or os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "launchpad.log"),
        maxBytes=10_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logging.getLogger("waitress").setLevel(log_level)
    logging.getLogger("waitress.queue").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    logging.info("Logging initialized")
    
configure_logging()

def str_to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def parse_list_setting(raw_value: str, default: str = "") -> list[str]:
    raw = (raw_value or default or "").strip()
    if not raw:
        return []
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../../templates",
        static_folder="../../static",
    )

    app.logger.info("Starting Launchpad application")

    # Core base config
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    app.config["SYSTEM_TIMEZONE"] = os.getenv("SYSTEM_TIMEZONE", "UTC")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_for=1)

    # Init DB
    import_by_scan_init_db()
    init_identity_db()
    init_mapping_db()
    seed_default_mappings()
    init_local_auth_db()
    init_settings_db()
    init_job_runs_db()
    init_rbac_db()
    init_staff_status_db()
    init_finance_db()
    snipe_catalog_init_db()
    checkout_assets_init_db()
    media_catalog_init_db()

    # Seed Finance defaults (safe/idempotent)
    ensure_efinance_daily_import_profile()

    init_api_keys_db()

    seed_permissions()
    ensure_default_local_admin()

    # -----------------------------
    # Authentication settings
    # DB-backed source of truth
    # -----------------------------

    # URL Config
    app.config["PREFERRED_URL_SCHEME"] = os.getenv("PREFERRED_URL_SCHEME", "https")

    # Sign-in methods
    app.config["AUTH_PRIMARY_METHOD"] = get_setting("auth.primary_method", "local")

    app.config["AUTH_LOCAL_ENABLED"] = get_bool_setting("auth.local.enabled", True)
    app.config["AUTH_LOCAL_MODE"] = get_setting("auth.local.mode", "breakglass_only")
    app.config["AUTH_LOCAL_HIDE_FORM_WHEN_RESTRICTED"] = get_bool_setting(
        "auth.local.hide_form_when_restricted", False
    )

    app.config["AUTH_MICROSOFT_OIDC_ENABLED"] = get_bool_setting(
        "auth.microsoft_oidc.enabled", False
    )
    app.config["AUTH_MICROSOFT_OIDC_TENANT_ID"] = get_setting(
        "auth.microsoft_oidc.tenant_id", "common"
    )
    app.config["AUTH_MICROSOFT_OIDC_CLIENT_ID"] = get_setting(
        "auth.microsoft_oidc.client_id", ""
    )
    app.config["AUTH_MICROSOFT_OIDC_CLIENT_SECRET"] = get_setting(
        "auth.microsoft_oidc.client_secret", ""
    )
    app.config["AUTH_MICROSOFT_OIDC_REDIRECT_URI"] = get_setting(
        "auth.microsoft_oidc.redirect_uri", ""
    )

    app.config["AUTH_GOOGLE_OIDC_ENABLED"] = get_bool_setting(
        "auth.google_oidc.enabled", False
    )
    app.config["GOOGLE_OIDC_CLIENT_ID"] = get_setting("auth.google_oidc.client_id", "")
    app.config["GOOGLE_OIDC_CLIENT_SECRET"] = get_setting(
        "auth.google_oidc.client_secret", ""
    )
    app.config["GOOGLE_OIDC_DISCOVERY_URL"] = (
        "https://accounts.google.com/.well-known/openid-configuration"
    )
    app.config["GOOGLE_OIDC_SCOPES"] = "openid email profile"
    app.config["GOOGLE_OIDC_REDIRECT_URI"] = get_setting(
        "auth.google_oidc.redirect_uri",
        f"{app.config['general.public_base_url']}/auth/google/callback"
        if app.config.get("general.public_base_url")
        else "",
    )
    app.config["AUTH_GOOGLE_HOSTED_DOMAIN"] = get_setting(
        "auth.google_oidc.hosted_domain", ""
    )

    app.config["AUTH_SAML_ENABLED"] = get_bool_setting("auth.saml.enabled", False)
    app.config["AUTH_SAML_IDP_TYPE"] = get_setting("auth.saml.idp_type", "generic")
    app.config["AUTH_SAML_METADATA_URL"] = get_setting("auth.saml.metadata_url", "")
    app.config["AUTH_SAML_METADATA_XML"] = get_setting("auth.saml.metadata_xml", "")
    app.config["AUTH_SAML_IDP_ENTITY_ID"] = get_setting("auth.saml.idp_entity_id", "")
    app.config["AUTH_SAML_SSO_URL"] = get_setting("auth.saml.sso_url", "")
    app.config["AUTH_SAML_SLO_URL"] = get_setting("auth.saml.slo_url", "")
    app.config["AUTH_SAML_X509_CERT"] = get_setting("auth.saml.x509_cert", "")
    app.config["AUTH_SAML_SP_ENTITY_ID"] = get_setting("auth.saml.sp_entity_id", "")
    app.config["AUTH_SAML_ACS_URL"] = get_setting("auth.saml.acs_url", "")
    app.config["AUTH_SAML_LOGOUT_URL"] = get_setting("auth.saml.logout_url", "")

    # Access control
    app.config["AUTH_REQUIRE_LOCAL_USER_FOR_SSO"] = get_bool_setting(
        "auth.access.require_local_user_for_sso", True
    )
    app.config["AUTH_MATCH_USER_BY"] = get_setting("auth.access.match_user_by", "email")
    app.config["AUTH_DENY_IF_USER_NOT_FOUND"] = get_bool_setting(
        "auth.access.deny_if_user_not_found", True
    )
    app.config["AUTH_DENY_IF_INACTIVE"] = get_bool_setting(
        "auth.access.deny_if_inactive", True
    )
    app.config["AUTH_ALLOWED_DOMAINS"] = parse_list_setting(
        get_setting("auth.access.allowed_domains", "")
    )
    app.config["AUTH_REQUIRED_GROUPS"] = parse_list_setting(
        get_setting("auth.access.required_groups", "")
    )
    app.config["AUTH_GROUP_MATCH_MODE"] = get_setting(
        "auth.access.required_groups_mode", "any"
    ).strip().lower()
    app.config["AUTH_ALLOW_BREAKGLASS_WITH_SSO"] = get_bool_setting(
        "auth.access.allow_breakglass_with_sso", True
    )

    # Session settings
    app.config["AUTH_REQUIRE_LOGIN_FOR_LAUNCHPAD"] = get_bool_setting(
        "security.require_login_for_launchpad", False
    )
    app.config["SESSION_IDLE_TIMEOUT_MINUTES"] = int(
        get_setting("security.session_idle_timeout_minutes", "30") or 30
    )
    app.config["SESSION_ABSOLUTE_TIMEOUT_HOURS"] = int(
        get_setting("security.session_absolute_timeout_hours", "8") or 8
    )
    app.config["SESSION_REMEMBER_ME_DAYS"] = int(
        get_setting("security.session_remember_me_days", "0") or 0
    )

    # Cookie settings
    app.config["SESSION_COOKIE_NAME"] = get_setting(
        "security.cookie_name", "launchpad_session"
    )
    app.config["SESSION_COOKIE_SECURE"] = get_bool_setting(
        "security.cookie_secure", False
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = get_bool_setting(
        "security.cookie_httponly", True
    )
    app.config["SESSION_COOKIE_SAMESITE"] = get_setting(
        "security.cookie_samesite", "Lax"
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        hours=app.config["SESSION_ABSOLUTE_TIMEOUT_HOURS"]
    )

    app.config["AUTH_EXEMPT_PATH_PREFIXES"] = [
        "/static/",
        "/login",
        "/logout",
        "/auth/google/start",
        "/auth/google/callback",
    ]

    app.config["GOOGLE_DIRECTORY_SERVICE_ACCOUNT_FILE"] = get_setting(
        "google.directory.service_account_file", ""
    )
    app.config["GOOGLE_DIRECTORY_DELEGATED_ADMIN"] = get_setting(
        "google.directory.delegated_admin", ""
    )

    # Init OAuth
    oauth.init_app(app)

    google_client_id = app.config["GOOGLE_OIDC_CLIENT_ID"]
    google_client_secret = app.config["GOOGLE_OIDC_CLIENT_SECRET"]

    if google_client_id and google_client_secret:
        oauth.register(
            name="google",
            client_id=google_client_id,
            client_secret=google_client_secret,
            server_metadata_url=app.config["GOOGLE_OIDC_DISCOVERY_URL"],
            client_kwargs={
                "scope": app.config["GOOGLE_OIDC_SCOPES"],
            },
        )

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(import_by_scan_bp)
    app.register_blueprint(snipe_catalog_bp)
    app.register_blueprint(launchpad_ui_bp)
    app.register_blueprint(snipeops_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(staff_status_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(finance_api_bp)
    app.register_blueprint(checkout_assets_bp)
    app.register_blueprint(media_catalog_bp)

    should_start_scheduler = True

    if app.debug:
        should_start_scheduler = os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    if should_start_scheduler:
        with app.app_context():
            configure_jobs()

    @app.before_request
    def check_initial_setup():
        if is_initial_setup_required():
            allowed_endpoints = {
                "setup.initial_setup",
                "auth.login",
            }

            if request.endpoint in allowed_endpoints:
                return None

            if request.endpoint and request.endpoint.endswith(".static"):
                return None

            return redirect(url_for("setup.initial_setup"))

    @app.before_request
    def enforce_session_rules():
        path = request.path or "/"

        for prefix in app.config.get("AUTH_EXEMPT_PATH_PREFIXES", []):
            if path.startswith(prefix):
                return None

        if session.get("is_authenticated"):
            now = utc_now()

            authenticated_at = session.get("authenticated_at")
            last_activity = session.get("last_activity")

            try:
                if authenticated_at:
                    auth_dt = datetime.fromisoformat(authenticated_at)
                    max_hours = app.config.get("SESSION_ABSOLUTE_TIMEOUT_HOURS", 8)
                    if now - auth_dt > timedelta(hours=max_hours):
                        session.clear()
                        flash("Your session expired. Please sign in again.", "error")
                        return redirect(url_for("auth.login", next=path))

                if last_activity:
                    last_dt = datetime.fromisoformat(last_activity)
                    idle_minutes = app.config.get("SESSION_IDLE_TIMEOUT_MINUTES", 30)
                    if now - last_dt > timedelta(minutes=idle_minutes):
                        session.clear()
                        flash("You were signed out due to inactivity.", "error")
                        return redirect(url_for("auth.login", next=path))
            except Exception:
                session.clear()
                flash("Your session was reset. Please sign in again.", "error")
                return redirect(url_for("auth.login", next=path))

            session["last_activity"] = now.isoformat()

        if app.config.get("AUTH_REQUIRE_LOGIN_FOR_LAUNCHPAD", False):
            if not session.get("is_authenticated"):
                return redirect(url_for("auth.login", next=path))

        return None

    @app.template_filter("localtime")
    def localtime_filter(value):
        return format_system_time(value)

    @app.template_filter("localdate")
    def localdate_filter(value):
        if not value:
            return ""

        raw = str(value).strip()
        if not raw:
            return ""

        date_format = get_setting("general.date_format", "mdy") or "mdy"

        try:
            if "T" in raw:
                dt = datetime.fromisoformat(raw)
                target_date = dt.date()
            else:
                target_date = date.fromisoformat(raw)
        except Exception:
            return raw

        if date_format == "dmy":
            return target_date.strftime("%m/%d/%Y")
        if date_format == "ymd":
            return target_date.strftime("%Y-%m-%d")

        # default mdy
        return target_date.strftime("%m/%d/%Y")

    @app.context_processor
    def inject_global_settings():
        general_settings = {
            "organization_name": get_setting("general.organization_name", ""),
            "footer_text": get_setting(
                "general.footer_text",
                "Sheridan School District • Internal Tech Ops",
            ),
            "support_email": get_setting("general.support_email", ""),
            "helpdesk_url": get_setting("general.helpdesk_url", ""),
            "announcement_enabled": get_bool_setting(
                "general.announcement_enabled", False
            ),
            "announcement_text": get_setting("general.announcement_text", ""),
            "timezone": get_setting(
                "general.timezone", app.config.get("SYSTEM_TIMEZONE", "UTC")
            ),
            "language": get_setting("general.language", "en"),
            "date_format": get_setting("general.date_format", "mdy"),
            "time_format": get_setting("general.time_format", "12h"),
        }

        current_user_theme = session.get("theme_preference", "light")

        if session.get("is_authenticated") and session.get("user_id"):
            user = get_user_by_id(session["user_id"])
            if user:
                current_user_theme = user.get("theme_preference") or "light"
                session["theme_preference"] = current_user_theme

        if current_user_theme not in ("light", "dark"):
            current_user_theme = "light"

        return {
            "SYSTEM_TIMEZONE": general_settings["timezone"],
            "general_settings": general_settings,
            "current_user_theme": current_user_theme,
        }

    app.logger.info("Launchpad application startup complete")
    return app