from flask import Blueprint

bp = Blueprint(
    "finance",
    __name__,
    url_prefix="/finance",
    template_folder="templates",
    static_folder="static",
)

from . import routes  # noqa: E402,F401
from . import ledger_routes  # noqa: E402,F401
