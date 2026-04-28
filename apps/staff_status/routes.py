from datetime import date, timedelta

from flask import abort, jsonify, redirect, render_template, request, session, url_for, Response
import time, queue
from modules.core.settings.settings_service import get_setting

from .access_service import (
    can_access_department,
    has_staff_status_admin,
    list_accessible_departments_for_user,
    can_operate_department,
)

from .blueprint import bp
from .service import (
    create_absence,
    create_location,
    delete_absence,
    delete_location,
    get_board_rows_for_department,
    get_department_by_board_token,
    get_department_by_kiosk_token,
    get_department_overview_analytics,
    get_overview_range_options,
    list_active_users_for_department,
    list_enabled_departments,
    list_locations_for_department,
    list_locations_for_department_admin,
    list_recent_absences_for_department,
    normalize_overview_range,
    rotate_board_token,
    rotate_kiosk_token,
    seed_department_locations_if_empty,
    sync_departments_from_users,
    update_absence,
    update_location,
    update_user_status,
    build_public_url,
    get_department_record,
    reorder_locations_for_department,
    ABSENCE_DURATION_OPTIONS,
    build_absence_csv_export,
    build_absence_pdf_export,
    list_absences_for_department,
    resolve_absence_duration,
    get_current_school_year_range,
    get_school_year_rollover_reminder,
    get_department_absence_usage_summary,
)
from modules.core.auth.decorators import login_required, require_permission
from modules.core.identity.user_service import get_user_by_id

from tasks.events import publish_department_update, subscribe, unsubscribe

@bp.route("/")
@login_required
def index():
    sync_departments_from_users()

    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    departments = list_accessible_departments_for_user(user_id)

    if not departments:
        return render_template(
            "staff_status/index.html",
            departments=[],
            active_tab="home",
            no_departments_assigned=True,
            is_staff_status_admin=has_staff_status_admin(user_id),
        )

    if len(departments) == 1:
        return redirect(
            url_for(
                "staff_status.department_overview",
                department_name=departments[0]["department_name"],
                active_tab="overview",
            )
        )

    return render_template(
        "staff_status/index.html",
        departments=departments,
        active_tab="home",
        no_departments_assigned=False,
        is_staff_status_admin=has_staff_status_admin(user_id),
    )


@bp.route("/<department_name>")
@login_required
def department_overview(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    seed_department_locations_if_empty(department_name)

    accessible_departments = list_accessible_departments_for_user(user_id)

    range_key = normalize_overview_range(request.args.get("range", "30d"))

    overview_analytics = get_department_overview_analytics(
        department_name,
        range_key,
    )

    highlight_7_day = (date.today() + timedelta(days=7)).isoformat()

    upcoming_absences = list_recent_absences_for_department(
        department_name,
        limit=10,
        sort_by="start_date",
        sort_dir="asc",
        view="upcoming",
    )

    absence_usage_payload = get_department_absence_usage_summary(
        department_name=department_name,
    )

    school_year = get_current_school_year_range()
    school_year_rollover_reminder = get_school_year_rollover_reminder()

    return render_template(
        "staff_status/department_overview.html",
        department_name=department_name,
        active_tab="overview",
        selected_range=range_key,
        range_options=get_overview_range_options(),
        overview_analytics=overview_analytics,
        upcoming_absences=upcoming_absences,
        absence_usage_summary=absence_usage_payload["rows"],
        absence_usage_school_year=absence_usage_payload["school_year"],
        school_year=school_year,
        school_year_rollover_reminder=school_year_rollover_reminder,
        accessible_department_count=len(accessible_departments),
        is_staff_status_admin=has_staff_status_admin(user_id),
        highlight_7_day=highlight_7_day,
    )
    
@bp.route("/<department_name>/overview/data")
@login_required
def department_overview_data(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    range_key = normalize_overview_range(request.args.get("range", "30d"))

    analytics = get_department_overview_analytics(
        department_name,
        range_key,
    )

    response = jsonify(
        {
            "ok": True,
            "department_name": department_name,
            "analytics": analytics,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response

@bp.route("/<department_name>/locations", methods=["GET", "POST"])
@login_required
def locations(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    seed_department_locations_if_empty(department_name)
    accessible_departments = list_accessible_departments_for_user(user_id)
    can_operate = can_operate_department(user_id, department_name)

    if request.method == "POST":
        if not can_operate:
            abort(403)

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

        return redirect(
            url_for(
                "staff_status.locations",
                department_name=department_name,
                active_tab="locations",
            )
        )

    return render_template(
        "staff_status/locations.html",
        department_name=department_name,
        locations=list_locations_for_department_admin(department_name),
        active_tab="locations",
        accessible_department_count=len(accessible_departments),
        is_staff_status_admin=has_staff_status_admin(user_id),
        can_operate=can_operate,
    )

@bp.route("/<department_name>/locations/reorder", methods=["POST"])
@login_required
def locations_reorder(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    if not can_operate_department(user_id, department_name):
        abort(403)

    payload = request.get_json(silent=True) or {}
    location_ids = payload.get("location_ids") or []

    normalized_location_ids = []
    for raw_location_id in location_ids:
        try:
            location_id = int(raw_location_id)
        except (TypeError, ValueError):
            continue

        if location_id > 0:
            normalized_location_ids.append(location_id)

    if not normalized_location_ids:
        return jsonify({
            "ok": False,
            "error": "No locations were provided.",
        }), 400

    reorder_locations_for_department(
        department_name=department_name,
        location_ids=normalized_location_ids,
    )

    return jsonify({
        "ok": True,
        "updated_count": len(normalized_location_ids),
    })

@bp.route("/<department_name>/board")
@login_required
def board(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    accessible_departments = list_accessible_departments_for_user(user_id)
    refresh_seconds = 30
    app_timezone = get_setting("general.timezone", "America/Chicago") or "America/Chicago"

    return render_template(
        "staff_status/board.html",
        department_name=department_name,
        board_rows=get_board_rows_for_department(department_name),
        refresh_seconds=refresh_seconds,
        active_tab="board",
        app_timezone=app_timezone,
        stream_url=url_for("staff_status.board_stream", department_name=department_name),
        accessible_department_count=len(accessible_departments),
        is_staff_status_admin=has_staff_status_admin(user_id),
    )
    
@bp.route("/<department_name>/board/stream")
@login_required
def board_stream(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

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
def board_data(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

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

    user_ids = request.form.getlist("user_ids")
    if not user_ids:
        legacy_user_id = request.form.get("user_id", type=int)
        if legacy_user_id:
            user_ids = [legacy_user_id]

    normalized_user_ids = []
    for raw_user_id in user_ids:
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            continue

        if user_id > 0:
            normalized_user_ids.append(user_id)

    normalized_user_ids = list(dict.fromkeys(normalized_user_ids))

    location_labels = request.form.getlist("location_labels")

    if not normalized_user_ids:
        return jsonify({"ok": False, "error": "At least one user must be selected."}), 400

    if not location_labels:
        return jsonify({"ok": False, "error": "At least one location must be selected."}), 400

    active_department_users = list_active_users_for_department(department_name)
    allowed_user_ids = {int(user["id"]) for user in active_department_users}

    selected_user_ids = [
        user_id
        for user_id in normalized_user_ids
        if user_id in allowed_user_ids
    ]

    if not selected_user_ids:
        return jsonify({
            "ok": False,
            "error": "No valid users were selected for this department.",
        }), 400

    source_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    source_device = request.user_agent.string[:255] if request.user_agent else None

    updated_count = 0

    for user_id in selected_user_ids:
        update_user_status(
            user_id=user_id,
            department_name=department_name,
            location_labels=location_labels,
            committed_by_user_id=None,
            committed_by_display_name=f"Kiosk:{department_name}",
            updated_by_source="kiosk_token",
            source_ip=source_ip,
            source_device=source_device,
        )
        updated_count += 1

    publish_department_update(department_name)

    return jsonify({
        "ok": True,
        "department_name": department_name,
        "updated_count": updated_count,
    })


@bp.route("/<department_name>/absences", methods=["GET", "POST"])
@login_required
def absences(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    accessible_departments = list_accessible_departments_for_user(user_id)
    can_operate = can_operate_department(user_id, department_name)
    users = list_active_users_for_department(department_name)
    absence_types = ["sick", "vacation", "personal", "other"]

    if request.method == "POST":
        if not can_operate:
            abort(403)

        actor = get_user_by_id(user_id)
        if not actor:
            abort(403)

        action = (request.form.get("action") or "").strip()

        if action == "update_absence":
            duration_mode, days_value, end_date = resolve_absence_duration(request.form)

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

        duration_mode, days_value, end_date = resolve_absence_duration(request.form)

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

    absence_type_filter = (request.args.get("absence_type") or "").strip().lower()
    current_absence_types = [absence_type_filter] if absence_type_filter else []

    current_user_ids = [
        item.strip()
        for item in request.args.getlist("user_ids")
        if item.strip()
    ]

    current_start_date = (request.args.get("start_date") or "").strip()
    current_end_date = (request.args.get("end_date") or "").strip()

    upcoming_absences = list_absences_for_department(
        department_name=department_name,
        timing="upcoming",
        absence_types=current_absence_types,
        user_ids=current_user_ids,
        start_date=current_start_date,
        end_date=current_end_date,
    )

    past_absences = list_absences_for_department(
        department_name=department_name,
        timing="past",
        absence_types=current_absence_types,
        user_ids=current_user_ids,
        start_date=current_start_date,
        end_date=current_end_date,
    )

    return render_template(
        "staff_status/absences.html",
        department_name=department_name,
        users=users,
        absence_types=absence_types,
        duration_options=ABSENCE_DURATION_OPTIONS,
        upcoming_absences=upcoming_absences,
        past_absences=past_absences,
        active_tab="absences",
        current_absence_types=current_absence_types,
        current_user_ids=current_user_ids,
        current_start_date=current_start_date,
        current_end_date=current_end_date,
        accessible_department_count=len(accessible_departments),
        is_staff_status_admin=has_staff_status_admin(user_id),
        can_operate=can_operate,
    )


@bp.route("/<department_name>/absences/export")
@login_required
def absences_export(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    absence_type_filter = (request.args.get("absence_type") or "").strip().lower()
    current_absence_types = [absence_type_filter] if absence_type_filter else []

    current_user_ids = [
        item.strip()
        for item in request.args.getlist("user_ids")
        if item.strip()
    ]

    timing = (request.args.get("timing") or "all").strip().lower()
    if timing not in {"upcoming", "past", "all"}:
        timing = "all"

    format_type = (request.args.get("format") or "csv").strip().lower()
    if format_type not in {"csv", "pdf"}:
        format_type = "csv"

    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()

    if format_type == "pdf":
        pdf_content, filename = build_absence_pdf_export(
            department_name=department_name,
            timing=timing,
            absence_types=current_absence_types,
            user_ids=current_user_ids,
            start_date=start_date,
            end_date=end_date,
        )

        return Response(
            pdf_content,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            },
        )

    csv_content, filename = build_absence_csv_export(
        department_name=department_name,
        timing=timing,
        absence_types=current_absence_types,
        user_ids=current_user_ids,
        start_date=start_date,
        end_date=end_date,
    )

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        },
    )


@bp.route("/board/<token>")
def board_public(token: str):
    department = get_department_by_board_token(token)
    if not department:
        abort(404)

    department_name = department["department_name"]
    refresh_seconds = 30
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

@bp.route("/<department_name>/urls")
@login_required
def urls(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    accessible_departments = list_accessible_departments_for_user(user_id)
    department = get_department_record(department_name) or {}

    kiosk_url = None
    board_url = None

    if department.get("kiosk_token"):
        kiosk_url = build_public_url(
            "staff_status.kiosk",
            token=department["kiosk_token"],
        )

    if department.get("board_token"):
        board_url = build_public_url(
            "staff_status.board_public",
            token=department["board_token"],
        )

    return render_template(
        "staff_status/urls.html",
        department_name=department_name,
        active_tab="urls",
        kiosk_url=kiosk_url,
        board_url=board_url,
        accessible_department_count=len(accessible_departments),
        is_staff_status_admin=has_staff_status_admin(user_id),
    )