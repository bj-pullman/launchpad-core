from flask import Blueprint

bp = Blueprint(
    "snipeops",
    __name__,
    url_prefix="/snipeops",
    template_folder="templates",
    static_folder="static/snipeops",
)