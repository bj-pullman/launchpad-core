from flask import Blueprint

launchpad_ui_bp = Blueprint(
    "launchpad_ui",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/launchpad_ui/static",
)

from . import routes  # noqa: E402,F401