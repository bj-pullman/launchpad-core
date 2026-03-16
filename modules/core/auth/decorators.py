from functools import wraps

from flask import flash, redirect, request, session, url_for


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("is_authenticated"):
            return redirect(url_for("auth.login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapper


def require_permission(permission_key: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not session.get("is_authenticated"):
                return redirect(url_for("auth.login", next=request.path))

            permissions = set(session.get("user_permissions", []))
            if permission_key not in permissions:
                flash("You do not have permission to access that page.", "error")
                return redirect(url_for("launchpad_ui.home"))

            return view_func(*args, **kwargs)

        return wrapper

    return decorator