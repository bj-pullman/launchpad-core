from decimal import Decimal, InvalidOperation

from flask import Blueprint


bp = Blueprint(
    "finance",
    __name__,
    url_prefix="/finance",
    template_folder="templates",
    static_folder="static",
)


@bp.app_template_filter("currency")
def format_currency(value) -> str:
    if value is None or value == "":
        return "$0.00"

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "$0.00"

    return f"${amount:,.2f}"


from . import routes  # noqa: E402,F401
from . import setup_guard_routes  # noqa: E402,F401
from . import ledger_routes  # noqa: E402,F401
from . import legacy_redirect_routes  # noqa: E402,F401