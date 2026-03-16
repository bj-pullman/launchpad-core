from flask import Blueprint, render_template, request, redirect, url_for, flash

from modules.core.auth.local_auth_service import (
    get_local_auth_by_username,
    create_local_auth_account,
    set_local_password,
)
from modules.core.auth.setup_service import is_initial_setup_required
from modules.core.identity.user_service import get_user_by_email

bp = Blueprint("setup", __name__, url_prefix="/setup")


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

        flash("Administrator password configured.", "success")
        return redirect(url_for("auth.login"))

    return render_template("setup/setup.html")