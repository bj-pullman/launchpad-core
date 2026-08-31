from flask import Blueprint, current_app, jsonify, request

from .service import (
    StaffStatusValidationError,
    create_pending_absence_request_from_public_submission,
    get_absence_form_integration_settings,
    send_pending_absence_request_email,
    verify_absence_form_integration_secret,
)


staff_status_integrations_bp = Blueprint(
    "staff_status_integrations",
    __name__,
    url_prefix="/api/integrations/staff-status",
)


def _bearer_token() -> str | None:
    authorization = (request.headers.get("Authorization") or "").strip()
    if not authorization.lower().startswith("bearer "):
        return None
    return authorization[7:].strip() or None


@staff_status_integrations_bp.route("/absence-requests", methods=["POST"])
def submit_absence_request():
    settings = get_absence_form_integration_settings()
    if not settings["enabled"]:
        return jsonify({
            "ok": False,
            "error": "Absence request integration is disabled.",
        }), 403

    token = _bearer_token()
    if not token:
        return jsonify({
            "ok": False,
            "error": "Authentication is required.",
        }), 401

    if not verify_absence_form_integration_secret(token):
        return jsonify({
            "ok": False,
            "error": "Authentication failed.",
        }), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "ok": False,
            "error": "Invalid request payload.",
        }), 400

    try:
        request_record, created = create_pending_absence_request_from_public_submission(
            payload=payload,
            source_ip=request.headers.get("X-Forwarded-For", request.remote_addr),
            source_user_agent=request.user_agent.string if request.user_agent else None,
        )
    except StaffStatusValidationError as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400

    email_sent = False
    if created:
        try:
            send_pending_absence_request_email(request_record)
            email_sent = True
        except Exception:
            current_app.logger.exception(
                "Staff Status absence request notification failed for request_id=%s",
                request_record.get("id"),
            )

    response = jsonify({
        "ok": True,
        "status": request_record["status"],
        "request_id": request_record["id"],
        "duplicate": not created,
        "email_sent": email_sent,
    })
    response.headers["Cache-Control"] = "no-store"
    return response
