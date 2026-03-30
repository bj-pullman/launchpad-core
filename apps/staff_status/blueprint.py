from flask import Blueprint

bp = Blueprint(
    "staff_status",
    __name__,
    url_prefix="/staff-status",
    template_folder="templates",
    static_folder="static",
)

from . import routes  # noqa: E402,F401