from flask import abort, jsonify, redirect, render_template, request, session, url_for, Response
import time, queue
from modules.core.settings.settings_service import get_setting

from .blueprint import bp
from .service import (
    create_absence,
    create_location,
    delete_absence,
    delete_location,
    get_board_rows_for_department,
    get_department_by_board_token,
    get_department_by_kiosk_token,
    list_active_users_for_department,
    list_enabled_departments,
    list_locations_for_department,
    list_locations_for_department_admin,
    list_recent_absences_for_department,
    rotate_board_token,
    rotate_kiosk_token,
    seed_department_locations_if_empty,
    sync_departments_from_users,
    update_absence,
    update_location,
    update_user_status,
    build_public_url,
)
from modules.core.auth.decorators import login_required, require_permission
from modules.core.identity.user_service import get_user_by_id

from tasks.events import publish_department_update, subscribe, unsubscribe

@bp.route("/")
@login_required
@require_permission("staff_status.home.view")
def index():
    sync_departments_from_users()
    departments = list_enabled_departments()

    if not departments:
        return render_template("staff_status/index.html", departments=[])

    if len(departments) == 1:
        return redirect(url_for(
            "staff_status.department_overview", 
            department_name=departments[0]["department_name"], 
            active_tab="overview",
            ))

    return render_template(
        "staff_status/index.html", 
        departments=departments, 
        active_tab="home",
        )


@bp.route("/<department_name>")
@login_required
@require_permission("staff_status.home.view")
def department_overview(department_name: str):
    seed_department_locations_if_empty(department_name)
    return render_template(
        "staff_status/department_overview.html",
        department_name=department_name,
        locations=list_locations_for_department(department_name),
        active_tab="overview",
    )

@bp.route("/<department_name>/locations", methods=["GET", "POST"])
@login_required
@require_permission("staff_status.home.view")
def locations(department_name: str):
    seed_department_locations_if_empty(department_name)

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "create":
            create_location(
                department_name=department_name,
                display_name=(request.form.get("display_name") or "").strip(),
                short_name=(request.form.get("short_name") or "").strip(),
                sort_order=request.form.get("sort_order", type=int),
            )
        elif action == "update":
            update_location(
                location_id=request.form.get("location_id", type=int),
                display_name=(request.form.get("display_name") or "").strip(),
                short_name=(request.form.get("short_name") or "").strip(),
                sort_order=request.form.get("sort_order", type=int),
                is_active=request.form.get("is_active") == "1",
            )
        elif action == "delete":
            delete_location(
                location_id=request.form.get("location_id", type=int),
            )

        return redirect(url_for(
            "staff_status.locations", 
            department_name=department_name, 
            active_tab="overview",))

    return render_template(
        "staff_status/locations.html",
        department_name=department_name,
        locations=list_locations_for_department_admin(department_name),
        active_tab="locations",
    )

@bp.route("/<department_name>/board")
@login_required
@require_permission("staff_status.board.view")
def board(department_name: str):
    refresh_seconds = int(get_setting("staff_status.board_refresh_seconds", "5") or "5")
    app_timezone = get_setting("general.timezone", "America/Chicago") or "America/Chicago"

    return render_template(
        "staff_status/board.html",
        department_name=department_name,
        board_rows=get_board_rows_for_department(department_name),
        refresh_seconds=refresh_seconds,
        active_tab="board",
        app_timezone=app_timezone,
        stream_url=url_for("staff_status.board_stream", department_name=department_name),
    )
    
@bp.route("/<department_name>/board/stream")
@login_required
@require_permission("staff_status.board.view")
def board_stream(department_name: str):
    department_name = department_name.strip()
    q = subscribe(department_name)

    def event_stream():
        try:
            yield ": connected\n\n"

            while True:
                try:
                    payload = q.get(timeout=25)
                    yield f"data: {payload}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(department_name, q)

    response = Response(event_stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@bp.route("/<department_name>/board/data")
@login_required
@require_permission("staff_status.board.view")
def board_data(department_name: str):
    rows = get_board_rows_for_department(department_name)

    response = jsonify(
        {
            "ok": True,
            "department_name": department_name,
            "rows": rows,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/kiosk/<token>")
def kiosk(token: str):
    department = get_department_by_kiosk_token(token)
    if not department:
        abort(404)

    department_name = department["department_name"]
    seed_department_locations_if_empty(department_name)

    return render_template(
        "staff_status/kiosk.html",
        kiosk_token=token,
        department_name=department_name,
        users=list_active_users_for_department(department_name),
        locations=list_locations_for_department(department_name),
        reset_seconds=2,
    )


@bp.route("/kiosk/<token>/submit", methods=["POST"])
def kiosk_submit(token: str):
    department = get_department_by_kiosk_token(token)
    if not department:
        return jsonify({"ok": False, "error": "Invalid kiosk token."}), 404

    department_name = department["department_name"]
    user_id = request.form.get("user_id", type=int)
    location_labels = request.form.getlist("location_labels")

    if not user_id:
        return jsonify({"ok": False, "error": "A user must be selected."}), 400
    if not location_labels:
        return jsonify({"ok": False, "error": "At least one location must be selected."}), 400

    update_user_status(
        user_id=user_id,
        department_name=department_name,
        location_labels=location_labels,
        committed_by_user_id=None,
        committed_by_display_name=f"Kiosk:{department_name}",
        updated_by_source="kiosk_token",
        source_ip=request.headers.get("X-Forwarded-For", request.remote_addr),
        source_device=request.user_agent.string[:255] if request.user_agent else None,
    )
    publish_department_update(department_name)

    return jsonify({"ok": True, "department_name": department_name})


@bp.route("/<department_name>/absences", methods=["GET", "POST"])
@login_required
@require_permission("staff_status.absences.manage")
def absences(department_name: str):
    users = list_active_users_for_department(department_name)
    absence_types = ["sick", "vacation", "personal", "other"]

    if request.method == "POST":
        actor = get_user_by_id(session["user_id"])
        if not actor:
            abort(403)

        action = (request.form.get("action") or "").strip()

        if action == "update_absence":
            duration_mode = (request.form.get("duration_mode") or "").strip()
            days_value_raw = (request.form.get("days_value") or "").strip()

            duration_lookup = {
                "quarter_day": 0.25,
                "half_day": 0.5,
                "three_quarter_day": 0.75,
                "full_day": 1.0,
            }

            if duration_mode == "multi_day":
                try:
                    days_value = float(days_value_raw)
                except ValueError:
                    days_value = None
            else:
                days_value = duration_lookup.get(duration_mode)

            if duration_mode != "multi_day":
                end_date = (request.form.get("start_date") or "").strip()
            else:
                end_date = (request.form.get("end_date") or "").strip()

            update_absence(
                absence_id=request.form.get("absence_id", type=int),
                absence_type=(request.form.get("absence_type") or "").strip().lower(),
                start_date=(request.form.get("start_date") or "").strip(),
                end_date=end_date,
                duration_mode=duration_mode,
                days_value=days_value,
                note=(request.form.get("note") or "").strip(),
                updated_by_user_id=actor["id"],
                updated_by_display_name=actor.get("display_name") or actor.get("email") or f"User {actor['id']}",
            )
            publish_department_update(department_name)
            return redirect(url_for("staff_status.absences", department_name=department_name))

        if action == "delete_absence":
            delete_absence(
                absence_id=request.form.get("absence_id", type=int),
                updated_by_user_id=actor["id"],
                updated_by_display_name=actor.get("display_name") or actor.get("email") or f"User {actor['id']}",
            )
            publish_department_update(department_name)
            return redirect(url_for("staff_status.absences", department_name=department_name))

        duration_mode = (request.form.get("duration_mode") or "").strip()
        days_value_raw = (request.form.get("days_value") or "").strip()

        duration_lookup = {
            "quarter_day": 0.25,
            "half_day": 0.5,
            "three_quarter_day": 0.75,
            "full_day": 1.0,
        }

        if duration_mode == "multi_day":
            try:
                days_value = float(days_value_raw)
            except ValueError:
                days_value = None
        else:
            days_value = duration_lookup.get(duration_mode)

        if duration_mode != "multi_day":
            end_date = (request.form.get("start_date") or "").strip()
        else:
            end_date = (request.form.get("end_date") or "").strip()

        create_absence(
            user_id=request.form.get("user_id", type=int),
            department_name=department_name,
            absence_type=(request.form.get("absence_type") or "").strip().lower(),
            start_date=(request.form.get("start_date") or "").strip(),
            end_date=end_date,
            duration_mode=duration_mode,
            days_value=days_value,
            note=(request.form.get("note") or "").strip(),
            created_by_user_id=actor["id"],
            created_by_display_name=actor.get("display_name") or actor.get("email") or f"User {actor['id']}",
        )
        publish_department_update(department_name)
        return redirect(url_for("staff_status.absences", department_name=department_name))

    sort_by = (request.args.get("sort") or "start_date").strip()
    sort_dir = (request.args.get("dir") or "desc").strip().lower()
    view = (request.args.get("view") or "active").strip().lower()

    absence_type_filter = (request.args.get("absence_type") or "").strip().lower()
    current_absence_types = [absence_type_filter] if absence_type_filter else []

    current_user_ids = [
        item.strip()
        for item in request.args.getlist("user_ids")
        if item.strip()
    ]

    return render_template(
        "staff_status/absences.html",
        department_name=department_name,
        users=users,
        absence_types=absence_types,
        recent_absences=list_recent_absences_for_department(
            department_name,
            sort_by=sort_by,
            sort_dir=sort_dir,
            view=view,
            absence_types=current_absence_types,
            user_ids=current_user_ids,
        ),
        active_tab="absences",
        current_sort=sort_by,
        current_dir=sort_dir,
        current_view=view,
        current_absence_types=current_absence_types,
        current_user_ids=current_user_ids,
    )

@bp.route("/board/<token>")
def board_public(token: str):
    department = get_department_by_board_token(token)
    if not department:
        abort(404)

    department_name = department["department_name"]
    refresh_seconds = int(get_setting("staff_status.board_refresh_seconds", "5") or "5")
    app_timezone = get_setting("general.timezone", "America/Chicago") or "America/Chicago"

    return render_template(
        "staff_status/board_public.html",
        department_name=department_name,
        board_rows=get_board_rows_for_department(department_name),
        refresh_seconds=refresh_seconds,
        board_token=token,
        app_timezone=app_timezone,
        stream_url=url_for("staff_status.board_public_stream", token=token),
    )
    
@bp.route("/board/<token>/stream")
def board_public_stream(token: str):
    department = get_department_by_board_token(token)
    if not department:
        return "", 404

    department_name = department["department_name"]
    q = subscribe(department_name)

    def event_stream():
        try:
            yield ": connected\n\n"

            while True:
                try:
                    payload = q.get(timeout=25)
                    yield f"data: {payload}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(department_name, q)

    response = Response(event_stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response
    
@bp.route("/board/<token>/data")
def board_public_data(token: str):
    department = get_department_by_board_token(token)
    if not department:
        response = jsonify({"ok": False, "error": "Invalid board token."})
        response.status_code = 404
        response.headers["Cache-Control"] = "no-store"
        return response

    department_name = department["department_name"]

    response = jsonify(
        {
            "ok": True,
            "department_name": department_name,
            "rows": get_board_rows_for_department(department_name),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response

@bp.route("/settings/<department_name>/rotate-kiosk-token", methods=["POST"])
@login_required
@require_permission("launchpad.settings.staff_status.manage")
def rotate_department_kiosk_token_for_settings(department_name: str):
    department = rotate_kiosk_token(department_name)
    return jsonify(
        {
            "ok": True,
            "department_name": department["department_name"],
            "kiosk_token": department["kiosk_token"],
            "kiosk_url": build_public_url(
                "staff_status.kiosk",
                token=department["kiosk_token"],
            ),
        }
    )


@bp.route("/settings/<department_name>/rotate-board-token", methods=["POST"])
@login_required
@require_permission("launchpad.settings.staff_status.manage")
def rotate_department_board_token_for_settings(department_name: str):
    department = rotate_board_token(department_name)
    return jsonify(
        {
            "ok": True,
            "department_name": department["department_name"],
            "board_token": department["board_token"],
            "board_url": build_public_url(
                "staff_status.board_public",
                token=department["board_token"],
            ),
        }
    )