import os
from datetime import datetime, timedelta, timezone
from functools import wraps
from modules.core.auth.google_directory import (
    build_directory_service,
    is_user_in_allowed_groups,
)

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from modules.core.auth.blueprint import bp
from modules.core.extensions import oauth

from modules.core.identity.user_service import get_user_by_email
from modules.core.auth.local_auth_service import verify_local_login
from modules.core.auth.permissions_service import get_user_permission_keys
from modules.core.identity.rbac_service import get_user_permission_keys, get_user_role_keys
from modules.core.auth.setup_service import is_initial_setup_required
from modules.core.auth.user_admin_service import update_last_login_at


def utcnow():
    return datetime.now(timezone.utc)


def to_iso(dt):
    return dt.isoformat()


def allowed_domain(email: str) -> bool:
    if not email or "@" not in email:
        return False

    domain = email.split("@", 1)[1].lower().strip()
    allowed = current_app.config.get("AUTH_ALLOWED_DOMAINS", [])
    return domain in allowed


def hosted_domain_ok(userinfo: dict) -> bool:
    if not current_app.config.get("AUTH_REQUIRE_GOOGLE_HOSTED_DOMAIN", False):
        return True

    allowed = current_app.config.get("AUTH_ALLOWED_DOMAINS", [])
    hd = (userinfo.get("hd") or "").lower().strip()
    return hd in allowed


def load_local_user(email: str):
    user = get_user_by_email(email)

    if not user:
        return None

    if not user.get("is_active", 0):
        return None

    return user


def start_user_session(local_user: dict, userinfo: dict, remember: bool = False):
    session.clear()

    now = utcnow()
    user_id = local_user["id"]

    session["is_authenticated"] = True
    session["user_id"] = user_id
    session["user_email"] = local_user["email"]
    session["user_name"] = userinfo.get("name", local_user.get("display_name", ""))
    session["user_role"] = next(iter(get_user_role_keys(user_id)), "viewer")
    session["user_roles"] = list(get_user_role_keys(user_id))
    session["user_permissions"] = list(get_user_permission_keys(user_id))
    session["google_sub"] = userinfo.get("sub", "")
    session["authenticated_at"] = to_iso(now)
    session["last_activity"] = to_iso(now)
    session["remember_me"] = bool(remember)

    remember_days = int(current_app.config.get("SESSION_REMEMBER_ME_DAYS", 0))
    if remember and remember_days > 0:
        session.permanent = True
        current_app.permanent_session_lifetime = timedelta(days=remember_days)
    else:
        session.permanent = False


def logout_current_user():
    session.clear()


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("is_authenticated"):
            return redirect(url_for("auth.login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapper

def user_passes_group_gate(email: str) -> bool:
    required_groups = current_app.config.get("AUTH_REQUIRED_GROUPS", [])
    match_mode = current_app.config.get("AUTH_GROUP_MATCH_MODE", "any")

    service_account_file = current_app.config.get("GOOGLE_DIRECTORY_SERVICE_ACCOUNT_FILE", "")
    delegated_admin = current_app.config.get("GOOGLE_DIRECTORY_DELEGATED_ADMIN", "")

    if not required_groups or not service_account_file or not delegated_admin:
        current_app.logger.warning("Group gate is not fully configured.")
        return False

    try:
        service = build_directory_service(service_account_file, delegated_admin)
        return is_user_in_allowed_groups(
            service=service,
            user_email=email,
            required_groups=required_groups,
            match_mode=match_mode,
        )
    except Exception as exc:
        current_app.logger.exception("Group membership check failed: %s", exc)
        return False
    
@bp.route("/login", methods=["GET"])
def login():
    if session.get("is_authenticated"):
        return redirect(request.args.get("next") or url_for("launchpad_ui.home"))

    next_url = request.args.get("next", "/")
    return render_template("launchpad_ui/login.html", next_url=next_url)

@bp.route("/login/local", methods=["POST"])
def local_login():
    if is_initial_setup_required():
        return redirect(url_for("setup.initial_setup"))
    
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    next_url = (request.form.get("next") or "/").strip()

    result = verify_local_login(username, password)
    if not result:
        current_app.logger.warning(
            "AUTH DENIED username=%s reason=invalid_local_login ip=%s",
            username,
            request.headers.get("X-Forwarded-For", request.remote_addr),
        )
        flash(
            "Username or password is incorrect.",
            "error",
        )
        return redirect(url_for("auth.login", next=next_url))

    local_user = result["user"]
    update_last_login_at(local_user["id"])

    current_app.logger.info(
        "AUTH SUCCESS username=%s source=local ip=%s",
        username,
        request.headers.get("X-Forwarded-For", request.remote_addr),
    )

    start_user_session(
        local_user=local_user,
        userinfo={
            "name": local_user.get("display_name", ""),
            "sub": f"local:{result['auth_account']['id']}",
        },
        remember=False,
    )

    flash(f"Signed in as {local_user['email']}.", "success")
    return redirect(next_url)


@bp.route("/auth/google/start", methods=["GET"])
def google_start():
    if is_initial_setup_required():
        return redirect(url_for("setup.initial_setup"))

    next_url = request.args.get("next", "/")
    remember = request.args.get("remember", "0")

    session["post_login_redirect"] = next_url
    session["requested_remember"] = "1" if remember == "1" else "0"

    redirect_uri = current_app.config["GOOGLE_OIDC_REDIRECT_URI"]

    auth_params = {}
    allowed_domains = current_app.config.get("AUTH_ALLOWED_DOMAINS", [])
    if allowed_domains:
        auth_params["hd"] = allowed_domains[0]

    return oauth.google.authorize_redirect(
        redirect_uri=redirect_uri,
        prompt="login",
        **auth_params,
    )

@bp.route("/auth/google/callback", methods=["GET"])
def google_callback():
    if is_initial_setup_required():
        return redirect(url_for("setup.initial_setup"))
    
    try:
        token = oauth.google.authorize_access_token()
    except Exception as exc:
        current_app.logger.exception("Google token exchange failed: %s", exc)
        flash("Google sign-in failed.", "error")
        return redirect(url_for("auth.login"))

    userinfo = token.get("userinfo")
    if not userinfo:
        try:
            userinfo = oauth.google.parse_id_token(token)
        except Exception as exc:
            current_app.logger.exception("Google ID token parsing failed: %s", exc)
            userinfo = None

    if not userinfo:
        flash("Google sign-in failed.", "error")
        return redirect(url_for("auth.login"))

    email = (userinfo.get("email") or "").strip().lower()

    if not email:
        flash("Google sign-in failed.", "error")
        return redirect(url_for("auth.login"))

    if not userinfo.get("email_verified", False):
        flash("Your account is not permitted to sign in.", "error")
        return redirect(url_for("auth.login"))

    if not allowed_domain(email):
        flash("Your account is not permitted to sign in.", "error")
        return redirect(url_for("auth.login"))

    if not hosted_domain_ok(userinfo):
        flash("Your account is not permitted to sign in.", "error")
        return redirect(url_for("auth.login"))

    local_user = load_local_user(email)
    if not local_user:
        current_app.logger.warning(
            "AUTH DENIED email=%s reason=no_active_local_user ip=%s",
            email,
            request.headers.get("X-Forwarded-For", request.remote_addr),
        )
        flash("Your account is not authorized for Launchpad.", "error")
        return redirect(url_for("auth.login"))
    
    update_last_login_at(local_user["id"])
    remember = session.get("requested_remember") == "1"

    current_app.logger.info(
        "AUTH SUCCESS email=%s source=google ip=%s",
        email,
        request.headers.get("X-Forwarded-For", request.remote_addr),
    )

    start_user_session(local_user, userinfo, remember=remember)

    next_url = session.pop("post_login_redirect", "/")
    session.pop("requested_remember", None)

    flash("Signed in successfully.", "success")
    return redirect(next_url)


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    email = session.get("user_email", "unknown")
    current_app.logger.info("User logged out: %s", email)

    logout_current_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))