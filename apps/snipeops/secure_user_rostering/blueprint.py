from flask import Blueprint

bp = Blueprint(
    "secure_user_rostering",
    __name__,
    url_prefix="/snipeops/secure-user-rostering",
    template_folder="templates",
    static_folder="static",
    static_url_path="/snipeops/secure-user-rostering/static",
)