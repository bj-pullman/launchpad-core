from datetime import datetime, timedelta, timezone
from functools import wraps

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

from modules.core.auth.google_directory import (
    build_directory_service,
    is_user_in_allowed_groups,
)
from modules.core.identity.user_service import get_user_by_email
from modules.core.auth.local_auth_service import verify_local_login
from modules.core.identity.rbac_service import get_user_permission_keys, get_user_role_keys
from modules.core.auth.setup_service import is_initial_setup_required
from modules.core.auth.user_admin_service import update_last_login_at
from modules.core.auth.auth_settings import get_auth_runtime_settings


def utcnow():
    return datetime.now(timezone.utc)


def to_iso(dt):
    return dt.isoformat()


def allowed_domain(email: str) -> bool:
    if not email or "@" not in email:
        return False

    settings = get_auth_settings()
    allowed = settings.get("allowed_domains", [])
    if not allowed:
        return True

    domain = email.split("@", 1)[1].lower().strip()
    return domain in allowed


def hosted_domain_ok(userinfo: dict) -> bool:
    settings = get_auth_settings()
    hosted_domain = (settings.get("google_hosted_domain") or "").strip().lower()
    if not hosted_domain:
        return True

    hd = (userinfo.get("hd") or "").lower().strip()
    return hd == hosted_domain


def load_local_user(email: str):
    settings = get_auth_settings()
    user = get_user_by_email(email)

    if not user:
        return None

    if settings.get("deny_if_inactive", True) and not user.get("is_active", 0):
        return None

    return user

def user_passes_group_gate(email: str) -> bool:
    settings = get_auth_settings()
    required_groups = settings.get("required_groups", [])
    match_mode = settings.get("required_groups_mode", "any")

    if not required_groups:
        return True

    service_account_file = settings.get("google_directory_service_account_file", "")
    delegated_admin = settings.get("google_directory_delegated_admin", "")

    if not service_account_file or not delegated_admin:
        current_app.logger.warning(
            "Group gate is enabled but Google Directory is not fully configured."
        )
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

def get_auth_settings():
    return get_auth_runtime_settings()

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
    session["theme_preference"] = local_user.get("theme_preference") or "light"
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


def ensure_google_oauth_client(settings: dict):
    client_id = settings.get("google_client_id", "")
    client_secret = settings.get("google_client_secret", "")

    if not client_id or not client_secret:
        return False

    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return True


@bp.route("/login", methods=["GET"])
def login():
    if session.get("is_authenticated"):
        return redirect(request.args.get("next") or url_for("launchpad_ui.home"))

    settings = get_auth_settings()
    next_url = request.args.get("next", "/")

    local_enabled = settings.get("local_enabled", True)
    local_mode = settings.get("local_mode", "breakglass_only")
    hide_local_form = settings.get("local_hide_form_when_restricted", False)

    show_local_form = False
    show_emergency_login = False

    if local_enabled and local_mode != "disabled":
        if local_mode == "breakglass_only":
            show_emergency_login = True
            show_local_form = not hide_local_form
        else:
            show_local_form = True

    return render_template(
        "launchpad_ui/login.html",
        next_url=next_url,
        show_local_form=show_local_form,
        show_emergency_login=show_emergency_login,
        google_oidc_enabled=settings.get("google_oidc_enabled", False),
        microsoft_oidc_enabled=settings.get("microsoft_oidc_enabled", False),
        saml_enabled=settings.get("saml_enabled", False),
        primary_method=settings.get("primary_method", "local"),
    )

@bp.route("/login/local", methods=["POST"])
def local_login():
    if is_initial_setup_required():
        return redirect(url_for("setup.initial_setup"))

    if not current_app.config.get("AUTH_LOCAL_ENABLED", True):
        flash("Local sign-in is disabled.", "error")
        return redirect(url_for("auth.login", next=request.form.get("next") or "/"))

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
        flash("Username or password is incorrect.", "error")
        return redirect(url_for("auth.login", next=next_url))

    auth_account = result["auth_account"]
    local_user = result["user"]

    local_mode = current_app.config.get("AUTH_LOCAL_MODE", "breakglass_only")
    if local_mode == "disabled":
        flash("Local sign-in is disabled.", "error")
        return redirect(url_for("auth.login", next=next_url))

    if local_mode == "breakglass_only" and not auth_account.get("is_breakglass", 0):
        flash("Local sign-in is restricted.", "error")
        return redirect(url_for("auth.login", next=next_url))

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
            "sub": f"local:{auth_account['id']}",
        },
        remember=False,
    )

    return redirect(next_url)

@bp.route("/login/emergency", methods=["GET"])
def emergency_login():
    if session.get("is_authenticated"):
        return redirect(request.args.get("next") or url_for("launchpad_ui.home"))

    settings = get_auth_settings()
    next_url = request.args.get("next", "/")

    if not settings.get("local_enabled", True):
        flash("Emergency local sign-in is not available.", "error")
        return redirect(url_for("auth.login", next=next_url))

    if settings.get("local_mode", "breakglass_only") == "disabled":
        flash("Emergency local sign-in is not available.", "error")
        return redirect(url_for("auth.login", next=next_url))

    return render_template(
        "launchpad_ui/emergency_login.html",
        next_url=next_url,
    )

@bp.route("/auth/google/start", methods=["GET"])
def google_start():
    if is_initial_setup_required():
        return redirect(url_for("setup.initial_setup"))

    settings = get_auth_settings()

    if not settings.get("google_oidc_enabled", False):
        flash("Google sign-in is not enabled.", "error")
        return redirect(url_for("auth.login"))

    if not ensure_google_oauth_client(settings):
        flash("Google sign-in is not fully configured.", "error")
        return redirect(url_for("auth.login"))

    redirect_uri = settings.get("google_redirect_uri", "").strip()
    if not redirect_uri:
        flash("Google sign-in is not fully configured.", "error")
        return redirect(url_for("auth.login"))

    next_url = request.args.get("next", "/")
    remember = request.args.get("remember", "0")

    session["post_login_redirect"] = next_url
    session["requested_remember"] = "1" if remember == "1" else "0"

    auth_params = {}
    hosted_domain = (settings.get("google_hosted_domain") or "").strip()
    if hosted_domain:
        auth_params["hd"] = hosted_domain

    return oauth.google.authorize_redirect(
        redirect_uri=redirect_uri,
        prompt="login",
        **auth_params,
    )


@bp.route("/auth/google/callback", methods=["GET"])
def google_callback():
    if is_initial_setup_required():
        return redirect(url_for("setup.initial_setup"))

    settings = get_auth_settings()

    if not settings.get("google_oidc_enabled", False):
        flash("Google sign-in is not enabled.", "error")
        return redirect(url_for("auth.login"))

    if not ensure_google_oauth_client(settings):
        flash("Google sign-in is not fully configured.", "error")
        return redirect(url_for("auth.login"))

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

    current_app.logger.info(
        "GOOGLE CALLBACK email=%s email_verified=%s hd=%s allowed_domains=%s hosted_domain=%s required_groups=%s",
        email,
        userinfo.get("email_verified", False),
        userinfo.get("hd"),
        settings.get("allowed_domains", []),
        settings.get("google_hosted_domain", ""),
        settings.get("required_groups", []),
    )

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

    if not user_passes_group_gate(email):
        flash("Your account is not permitted to sign in.", "error")
        return redirect(url_for("auth.login"))

    local_user = load_local_user(email)
    if not local_user and settings.get("require_local_user_for_sso", True):
        current_app.logger.warning(
            "AUTH DENIED email=%s reason=no_active_local_user ip=%s",
            email,
            request.headers.get("X-Forwarded-For", request.remote_addr),
        )
        flash("Your account is not authorized for Launchpad.", "error")
        return redirect(url_for("auth.login"))

    if not local_user and settings.get("deny_if_user_not_found", True):
        flash("Your account is not authorized for Launchpad.", "error")
        return redirect(url_for("auth.login"))

    if not local_user:
        flash("Your account is not authorized for Launchpad.", "error")
        return redirect(url_for("auth.login"))

    update_last_login_at(local_user["id"])
    remember = session.get("requested_remember") == "1"

    start_user_session(local_user, userinfo, remember=remember)

    next_url = session.pop("post_login_redirect", "/")
    session.pop("requested_remember", None)

    return redirect(next_url)


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    email = session.get("user_email", "unknown")
    current_app.logger.info("User logged out: %s", email)

    logout_current_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))