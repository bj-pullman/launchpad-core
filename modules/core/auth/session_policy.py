"""Database-backed session policy, with no process-wide per-user configuration."""
from datetime import datetime, timedelta, timezone
import secrets
from contextlib import closing

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature

from modules.core.settings.settings_db import get_connection


DEFAULTS = {
    "session_idle_timeout_minutes": "30",
    "session_absolute_timeout_hours": "8",
    "session_remember_me_days": "0",
    "session_keep_active": "false",
    "require_login_for_launchpad": "false",
    "cookie_secure": "false",
    "cookie_httponly": "true",
    "cookie_samesite": "Lax",
}
MAXIMUMS = {"session_idle_timeout_minutes": 525600, "session_absolute_timeout_hours": 87600,
            "session_remember_me_days": 3650}


def read_policy():
    if hasattr(g, "session_policy"):
        return g.session_policy
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT setting_key, setting_value FROM app_settings WHERE setting_key LIKE 'security.%'").fetchall()
    stored = {row["setting_key"]: row["setting_value"] for row in rows}
    values = {}
    for key, default in DEFAULTS.items():
        raw = stored.get("security." + key, default)
        if default in ("true", "false"):
            values[key] = str(raw).lower() in ("true", "1", "yes", "on")
        elif key == "cookie_samesite":
            values[key] = raw if raw in ("Lax", "Strict", "None") else "Lax"
        else:
            try:
                values[key] = min(MAXIMUMS[key], max(0, int(raw)))
            except (ValueError, TypeError):
                values[key] = int(default)
    g.session_policy = values
    return values


def timestamp(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Older deployments wrote UTC without an offset.
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def termination_reason(data, policy, now):
    if not data.get("is_authenticated"):
        return "authentication_state_invalid" if data.get("user_id") else None
    if not isinstance(data.get("user_id"), int) or data["user_id"] <= 0:
        return "authentication_state_invalid"
    for key in ("authenticated_at", "last_activity"):
        try:
            parsed = timestamp(data.get(key))
            if parsed > now + timedelta(minutes=5):
                return "invalid_" + key
        except (ValueError, TypeError, OverflowError):
            return "invalid_" + key
    age = now - timestamp(data["authenticated_at"])
    absolute = policy["session_absolute_timeout_hours"]
    idle = policy["session_idle_timeout_minutes"]
    if absolute and age >= timedelta(hours=absolute):
        return "absolute_timeout"
    if idle and now - timestamp(data["last_activity"]) >= timedelta(minutes=idle):
        return "idle_timeout"
    days = policy["session_remember_me_days"]
    if data.get("remember_me") and days and age >= timedelta(days=days):
        return "remember_me_timeout"
    return None


def clear_session(reason):
    if session.get("is_authenticated") or session.get("user_id"):
        current_app.logger.info("session_terminated reason=%s endpoint=%s method=%s", reason, request.endpoint, request.method)
    session.clear()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def require_csrf():
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not supplied or not secrets.compare_digest(supplied, session.get("csrf_token", "")):
        abort(400, "Invalid request token. Reload the page and try again.")


class PolicySessionInterface(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return read_policy()["cookie_secure"]

    def get_cookie_httponly(self, app):
        return read_policy()["cookie_httponly"]

    def get_cookie_samesite(self, app):
        policy = read_policy()
        value = policy["cookie_samesite"]
        return "Lax" if value == "None" and not policy["cookie_secure"] else value

    def open_session(self, app, request):
        signer = self.get_signing_serializer(app)
        if signer is None:
            return None
        value = request.cookies.get(self.get_cookie_name(app))
        if not value:
            return self.session_class()
        try:
            # Enforce authenticated age explicitly, including non-permanent cookies.
            # Flask's global max_age would otherwise defeat Never and Remember Me.
            data = signer.loads(value)
            if not data.get("is_authenticated"):
                # Preserve Flask's age limit for anonymous/OAuth bootstrap state.
                data = signer.loads(value, max_age=int(app.permanent_session_lifetime.total_seconds()))
            return self.session_class(data)
        except BadSignature:
            app.logger.info("session_rejected reason=invalid_cookie_signature")
            return self.session_class()

    def get_expiration_time(self, app, data):
        if not data.permanent:
            return None
        policy = read_policy()
        if not policy["session_remember_me_days"]:
            return None
        try:
            auth_at = timestamp(data.get("authenticated_at"))
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)
        limits = []
        if policy["session_remember_me_days"]:
            limits.append(auth_at + timedelta(days=policy["session_remember_me_days"]))
        if policy["session_absolute_timeout_hours"]:
            limits.append(auth_at + timedelta(hours=policy["session_absolute_timeout_hours"]))
        return min(limits) if limits else None


def enforce_session_rules():
    policy = read_policy()
    now = datetime.now(timezone.utc)
    reason = termination_reason(session, policy, now)
    if reason:
        clear_session(reason)
        from modules.core.auth.decorators import _wants_json_response
        if request.is_json or _wants_json_response() or request.path.endswith("/activity"):
            return jsonify(error="session_expired", reason=reason), 401
        return redirect(url_for("auth.login", next=request.path))
    # Polling and static files are not evidence of human activity. Shared client
    # marks fetches explicitly; successful navigations remain normal activity.
    background = request.headers.get("X-Launchpad-Background") == "1"
    static = request.endpoint and request.endpoint.endswith("static")
    if session.get("is_authenticated") and not background and not static:
        if request.path.endswith("/activity"):
            pass  # Validated by the POST handler, never a blind heartbeat.
        else:
            session["last_activity"] = now.isoformat()
    exempt = static or any(request.path.startswith(p) for p in current_app.config.get("AUTH_EXEMPT_PATH_PREFIXES", []))
    if policy["require_login_for_launchpad"] and not exempt and not session.get("is_authenticated"):
        return redirect(url_for("auth.login", next=request.path))


def register_session_policy(app):
    app.session_interface = PolicySessionInterface()
    app.before_request(enforce_session_rules)

    @app.after_request
    def private_session_responses(response):
        if session.accessed and not (request.endpoint and request.endpoint.endswith("static")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/auth/session/activity")
    def session_activity():
        if not session.get("is_authenticated"):
            return jsonify(error="authentication_required"), 401
        require_csrf()
        if read_policy()["session_keep_active"]:
            session["last_activity"] = datetime.now(timezone.utc).isoformat()
        return "", 204

    @app.context_processor
    def session_context():
        return {"csrf_token": csrf_token, "session_keep_active": read_policy()["session_keep_active"]}
