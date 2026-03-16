import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, flash, redirect, request, session, url_for

from apps.snipeops.import_by_scan.blueprint import bp as import_by_scan_bp
from apps.snipeops.import_by_scan.db import init_db
from apps.snipeops.snipe_catalog.blueprint import bp as snipe_catalog_bp
from apps.launchpad_ui import launchpad_ui_bp
from apps.snipeops.blueprint import bp as snipeops_bp

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

load_dotenv()


def str_to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def build_allowed_domains():
    raw = os.getenv("AUTH_ALLOWED_DOMAINS", "sheridanschools.org")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../../templates",
        static_folder="../../static",
    )

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    app.config["SYSTEM_TIMEZONE"] = os.getenv("SYSTEM_TIMEZONE", "UTC")

    # Google OIDC
    app.config["GOOGLE_OIDC_CLIENT_ID"] = os.getenv("GOOGLE_OIDC_CLIENT_ID", "")
    app.config["GOOGLE_OIDC_CLIENT_SECRET"] = os.getenv("GOOGLE_OIDC_CLIENT_SECRET", "")
    app.config["GOOGLE_OIDC_DISCOVERY_URL"] = "https://accounts.google.com/.well-known/openid-configuration"
    app.config["GOOGLE_OIDC_SCOPES"] = "openid email profile"
    app.config["GOOGLE_OIDC_REDIRECT_URI"] = os.getenv(
        "GOOGLE_OIDC_REDIRECT_URI",
        "http://localhost:5001/auth/google/callback",
    )

    # Auth behavior
    app.config["AUTH_ALLOWED_DOMAINS"] = build_allowed_domains()
    app.config["AUTH_REQUIRE_GOOGLE_HOSTED_DOMAIN"] = str_to_bool(
        os.getenv("AUTH_REQUIRE_GOOGLE_HOSTED_DOMAIN", "true")
    )
    app.config["AUTH_AUTO_PROVISION"] = str_to_bool(
        os.getenv("AUTH_AUTO_PROVISION", "false")
    )
    app.config["AUTH_DEFAULT_ROLE"] = os.getenv("AUTH_DEFAULT_ROLE", "viewer")
    app.config["AUTH_REQUIRE_LOGIN_FOR_LAUNCHPAD"] = str_to_bool(
        os.getenv("AUTH_REQUIRE_LOGIN_FOR_LAUNCHPAD", "false")
    )

    # Session settings
    app.config["SESSION_IDLE_TIMEOUT_MINUTES"] = int(
        os.getenv("SESSION_IDLE_TIMEOUT_MINUTES", "30")
    )
    app.config["SESSION_ABSOLUTE_TIMEOUT_HOURS"] = int(
        os.getenv("SESSION_ABSOLUTE_TIMEOUT_HOURS", "8")
    )
    app.config["SESSION_REMEMBER_ME_DAYS"] = int(
        os.getenv("SESSION_REMEMBER_ME_DAYS", "0")
    )

    # Cookie settings
    app.config["SESSION_COOKIE_NAME"] = os.getenv("SESSION_COOKIE_NAME", "launchpad_session")
    app.config["SESSION_COOKIE_SECURE"] = str_to_bool(
        os.getenv("SESSION_COOKIE_SECURE", "false")
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = str_to_bool(
        os.getenv("SESSION_COOKIE_HTTPONLY", "true")
    )
    app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
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

    def build_required_groups():
        raw = os.getenv("AUTH_REQUIRED_GROUPS", "")
        return [item.strip().lower() for item in raw.split(",") if item.strip()]

    app.config["AUTH_REQUIRED_GROUPS"] = build_required_groups()
    app.config["AUTH_GROUP_MATCH_MODE"] = os.getenv("AUTH_GROUP_MATCH_MODE", "any").strip().lower()

    app.config["GOOGLE_DIRECTORY_SERVICE_ACCOUNT_FILE"] = os.getenv(
        "GOOGLE_DIRECTORY_SERVICE_ACCOUNT_FILE", ""
    )
    app.config["GOOGLE_DIRECTORY_DELEGATED_ADMIN"] = os.getenv(
        "GOOGLE_DIRECTORY_DELEGATED_ADMIN", ""
    )

    # Init DB
    init_db()
    init_identity_db()
    init_local_auth_db()
    init_settings_db()
    init_rbac_db()

    seed_permissions()
    ensure_default_local_admin()

    # Init OAuth
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=app.config["GOOGLE_OIDC_CLIENT_ID"],
        client_secret=app.config["GOOGLE_OIDC_CLIENT_SECRET"],
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

            session["last_activity"] = now.isoformat()

        if app.config.get("AUTH_REQUIRE_LOGIN_FOR_LAUNCHPAD", False):
            if not session.get("is_authenticated"):
                return redirect(url_for("auth.login", next=path))

        return None

    @app.template_filter("localtime")
    def localtime_filter(value):
        return format_system_time(value)

    @app.context_processor
    def inject_global_settings():
        general_settings = {
            "organization_name": get_setting("general.organization_name", ""),
            "portal_name": get_setting("general.portal_name", "Launchpad"),
            "footer_text": get_setting("general.footer_text", "Sheridan School District • Internal Tech Ops"),
            "support_email": get_setting("general.support_email", ""),
            "helpdesk_url": get_setting("general.helpdesk_url", ""),
            "announcement_enabled": get_bool_setting("general.announcement_enabled", False),
            "announcement_text": get_setting("general.announcement_text", ""),
            "timezone": get_setting("general.timezone", app.config.get("SYSTEM_TIMEZONE", "UTC")),
            "language": get_setting("general.language", "en"),
            "date_format": get_setting("general.date_format", "mdy"),
            "time_format": get_setting("general.time_format", "12h"),
        }

        return {
            "SYSTEM_TIMEZONE": general_settings["timezone"],
            "general_settings": general_settings,
        }

    return app