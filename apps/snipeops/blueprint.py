from flask import Blueprint, render_template

from modules.core.auth.decorators import login_required, require_permission

bp = Blueprint(
    "snipeops",
    __name__,
    url_prefix="/snipeops",
    template_folder="templates",
    static_folder="static/snipeops",
)

@bp.route("/")
@login_required
@require_permission("snipeops.home.view")
def index():
    return render_template("snipeops/home.html")