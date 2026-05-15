from flask import Blueprint, request, abort, jsonify

from modules.core.api_keys.service import verify_api_key, mark_api_key_used

finance_api_bp = Blueprint("finance_api", __name__, url_prefix="/api/finance")


def require_api_key(action_name):
    def decorator(func):
        def wrapper(*args, **kwargs):
            api_key = verify_api_key(request.headers.get("X-Launchpad-API-Key"))

            if not api_key:
                abort(401)

            response = func(*args, **kwargs)

            mark_api_key_used(
                api_key_id=api_key["id"],
                action=action_name,
            )

            return response
        return wrapper
    return decorator


@finance_api_bp.route("/imports/efinance", methods=["POST"])
@require_api_key("finance.import.efinance.upload")
def import_efinance():
    upload = request.files.get("file")

    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    # process file...

    return jsonify({"ok": True})