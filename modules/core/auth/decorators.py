from functools import wraps

from flask import flash, jsonify, redirect, request, session, url_for


def _wants_json_response():
    accept = request.headers.get("Accept", "")
    requested_with = request.headers.get("X-Requested-With", "")

    return (
        requested_with in {"fetch", "XMLHttpRequest"}
        or "application/json" in accept
        or "/api/" in request.path
        or request.path.endswith("/sync")
        or request.path.endswith("/run")
    )


def _auth_failed_response():
    if _wants_json_response():
        return jsonify({
            "ok": False,
            "error": "Authentication required. Please sign in again.",
            "redirect": url_for("auth.login", next=request.path),
        }), 401

    return redirect(url_for("auth.login", next=request.path))


def _permission_failed_response():
    if _wants_json_response():
        return jsonify({
            "ok": False,
            "error": "Access denied. You do not have permission to perform this action.",
        }), 403

    flash("You do not have permission to access that page.", "error")
    return redirect(url_for("launchpad_ui.home"))


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("is_authenticated"):
            return _auth_failed_response()

        return view_func(*args, **kwargs)

    return wrapper


def require_permission(permission_key: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not session.get("is_authenticated"):
                return _auth_failed_response()

            permissions = set(session.get("user_permissions", []))

            if permission_key not in permissions:
                return _permission_failed_response()

            return view_func(*args, **kwargs)

        return wrapper

    return decorator