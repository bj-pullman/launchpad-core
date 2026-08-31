from datetime import date, timedelta
from urllib.parse import urlencode

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for, Response
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
    reject_pending_absence_request,
    approve_pending_absence_request,
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
    normalize_absence_table_sort,
    resolve_absence_duration,
    resolve_absence_report_date_range,
    get_absence_report_date_range_options,
    get_current_school_year_range,
    get_school_year_rollover_reminder,
    get_department_absence_usage_summary,
    get_pending_absence_request_by_id,
    StaffStatusValidationError,
    PendingAbsenceRequestStateError,
)
from modules.core.auth.decorators import login_required, require_permission
from modules.core.identity.user_service import get_user_by_id

from tasks.events import publish_department_update, subscribe, unsubscribe


def _actor_display_name(actor: dict) -> str:
    return actor.get("display_name") or actor.get("email") or f"User {actor['id']}"


def _can_review_absence_request(user_id: int, actor: dict, request_record: dict) -> bool:
    if has_staff_status_admin(user_id):
        return True

    actor_email = (actor.get("email") or "").strip().lower()
    manager_email = (request_record.get("approval_manager_email") or "").strip().lower()
    return bool(actor_email and manager_email and actor_email == manager_email)


ABSENCE_TABLE_DEFAULT_DATE_RANGE_KEY = "all"
ABSENCE_TABLE_SORT_LABELS = {
    "user": "User",
    "type": "Type",
    "start": "Start",
    "end": "End",
    "time": "Time",
    "duration": "Duration",
    "days": "Days",
    "hours": "Hours",
    "entered_by": "Entered By",
    "created": "Created",
}


def _format_absence_helper_date(value) -> str:
    if isinstance(value, date):
        parsed_date = value
    else:
        try:
            parsed_date = date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return ""

    return parsed_date.strftime("%m/%d/%Y")


def _absence_range_summary(range_info: dict) -> str:
    if range_info["key"] == "all":
        return "All Dates"

    return (
        f"{range_info['label']}: "
        f"{_format_absence_helper_date(range_info['start_date_iso'])} "
        f"to {_format_absence_helper_date(range_info['end_date_iso'])}"
    )


def _build_absence_date_range_options(*, include_all: bool = False) -> list[dict]:
    options = []

    if include_all:
        options.append({
            "key": "all",
            "label": "All Dates",
            "resolved_label": "All Dates",
            "start_date_iso": "",
            "end_date_iso": "",
            "helper_text": "All Dates",
        })

    for option in get_absence_report_date_range_options():
        option_payload = dict(option)

        if option_payload["key"] == "custom":
            option_payload.update({
                "resolved_label": option_payload["label"],
                "start_date_iso": "",
                "end_date_iso": "",
                "helper_text": "Custom Range: choose a start and end date.",
            })
        else:
            resolved = resolve_absence_report_date_range(range_key=option_payload["key"])
            option_payload.update({
                "resolved_label": resolved["label"],
                "start_date_iso": resolved["start_date_iso"],
                "end_date_iso": resolved["end_date_iso"],
                "helper_text": _absence_range_summary(resolved),
            })

        options.append(option_payload)

    return options


def _build_absence_table_url(department_name: str, params: dict) -> str:
    clean_pairs = []

    for key, value in params.items():
        if value in (None, ""):
            continue

        if isinstance(value, list):
            clean_pairs.extend((key, item) for item in value if item not in (None, ""))
        else:
            clean_pairs.append((key, value))

    path = url_for("staff_status.absences", department_name=department_name)
    if not clean_pairs:
        return path

    return f"{path}?{urlencode(clean_pairs, doseq=True)}"


def _build_absence_table_filter_params(
    *,
    date_range_key: str,
    custom_start_date: str,
    custom_end_date: str,
    absence_type_filter: str,
    user_ids: list[str],
) -> dict:
    params = {}

    if date_range_key and date_range_key != ABSENCE_TABLE_DEFAULT_DATE_RANGE_KEY:
        params["table_date_range"] = date_range_key

    if date_range_key == "custom":
        params["table_start_date"] = custom_start_date
        params["table_end_date"] = custom_end_date

    if absence_type_filter:
        params["table_absence_type"] = absence_type_filter

    if user_ids:
        params["table_user_ids"] = user_ids

    return params


def _build_absence_table_filter_labels(
    *,
    date_range: dict,
    absence_type_filter: str,
    user_ids: list[str],
    users: list[dict],
) -> list[str]:
    labels = []

    if date_range["key"] != ABSENCE_TABLE_DEFAULT_DATE_RANGE_KEY:
        labels.append(f"Date: {_absence_range_summary(date_range)}")

    if absence_type_filter:
        labels.append(f"Type: {absence_type_filter.title()}")

    if user_ids:
        user_lookup = {
            str(user["id"]): user.get("resolved_display_name") or f"User {user['id']}"
            for user in users
        }
        selected_names = [user_lookup.get(str(user_id), f"User {user_id}") for user_id in user_ids]
        if len(selected_names) <= 2:
            labels.append(f"Users: {', '.join(selected_names)}")
        else:
            labels.append(f"Users: {', '.join(selected_names[:2])} + {len(selected_names) - 2} more")

    return labels


def _build_absence_table_sort_urls(
    *,
    department_name: str,
    filter_params: dict,
    current_sort_key: str | None,
    current_sort_direction: str,
    default_sort_key: str,
    default_sort_direction: str,
) -> dict:
    urls = {}

    for sort_key in ABSENCE_TABLE_SORT_LABELS:
        if current_sort_key == sort_key:
            next_direction = "desc" if current_sort_direction == "asc" else "asc"
        elif not current_sort_key and default_sort_key == sort_key:
            next_direction = "desc" if default_sort_direction == "asc" else "asc"
        else:
            next_direction = "asc"

        sort_params = dict(filter_params)
        sort_params["table_sort"] = sort_key
        sort_params["table_direction"] = next_direction
        urls[sort_key] = _build_absence_table_url(department_name, sort_params)

    return urls


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

            try:
                update_absence(
                    absence_id=request.form.get("absence_id", type=int),
                    department_name=department_name,
                    absence_type=(request.form.get("absence_type") or "").strip().lower(),
                    start_date=(request.form.get("start_date") or "").strip(),
                    end_date=end_date,
                    duration_mode=duration_mode,
                    days_value=days_value,
                    start_time=(request.form.get("start_time") or "").strip(),
                    note=(request.form.get("note") or "").strip(),
                    updated_by_user_id=actor["id"],
                    updated_by_display_name=actor.get("display_name") or actor.get("email") or f"User {actor['id']}",
                )
            except StaffStatusValidationError as exc:
                flash(str(exc), "error")
                return redirect(url_for("staff_status.absences", department_name=department_name))

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

        try:
            create_absence(
                user_id=request.form.get("user_id", type=int),
                department_name=department_name,
                absence_type=(request.form.get("absence_type") or "").strip().lower(),
                start_date=(request.form.get("start_date") or "").strip(),
                end_date=end_date,
                duration_mode=duration_mode,
                days_value=days_value,
                start_time=(request.form.get("start_time") or "").strip(),
                note=(request.form.get("note") or "").strip(),
                created_by_user_id=actor["id"],
                created_by_display_name=actor.get("display_name") or actor.get("email") or f"User {actor['id']}",
            )
        except StaffStatusValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("staff_status.absences", department_name=department_name))

        publish_department_update(department_name)
        return redirect(url_for("staff_status.absences", department_name=department_name))

    table_absence_type_filter = (request.args.get("table_absence_type") or "").strip().lower()
    if table_absence_type_filter not in absence_types:
        table_absence_type_filter = ""
    current_table_absence_types = [table_absence_type_filter] if table_absence_type_filter else []

    current_table_user_ids = [
        item.strip()
        for item in request.args.getlist("table_user_ids")
        if item.strip()
    ]

    table_date_range_options = _build_absence_date_range_options(include_all=True)
    report_date_range_options = _build_absence_date_range_options(include_all=False)
    valid_table_date_range_keys = {option["key"] for option in table_date_range_options}
    current_table_date_range_key = (
        request.args.get("table_date_range") or ABSENCE_TABLE_DEFAULT_DATE_RANGE_KEY
    ).strip().lower()
    if current_table_date_range_key not in valid_table_date_range_keys:
        current_table_date_range_key = ABSENCE_TABLE_DEFAULT_DATE_RANGE_KEY

    current_table_custom_start_date = (request.args.get("table_start_date") or "").strip()
    current_table_custom_end_date = (request.args.get("table_end_date") or "").strip()

    try:
        if current_table_date_range_key == "all":
            table_range = {
                "key": "all",
                "label": "All Dates",
                "start_date_iso": None,
                "end_date_iso": None,
            }
        else:
            table_range = resolve_absence_report_date_range(
                range_key=current_table_date_range_key,
                custom_start_date=current_table_custom_start_date,
                custom_end_date=current_table_custom_end_date,
            )
    except StaffStatusValidationError as exc:
        flash(str(exc), "error")
        table_range = {
            "key": "all",
            "label": "All Dates",
            "start_date_iso": None,
            "end_date_iso": None,
        }

    current_table_sort_key, current_table_sort_direction = normalize_absence_table_sort(
        request.args.get("table_sort"),
        request.args.get("table_direction"),
    )

    current_start_date = table_range["start_date_iso"]
    current_end_date = table_range["end_date_iso"]

    past_absences = list_absences_for_department(
        department_name=department_name,
        timing="past",
        absence_types=current_table_absence_types,
        user_ids=current_table_user_ids,
        start_date=current_start_date,
        end_date=current_end_date,
        sort_key=current_table_sort_key,
        sort_direction=current_table_sort_direction,
    )

    table_filter_params = _build_absence_table_filter_params(
        date_range_key=table_range["key"],
        custom_start_date=current_table_custom_start_date if table_range["key"] == "custom" else "",
        custom_end_date=current_table_custom_end_date if table_range["key"] == "custom" else "",
        absence_type_filter=table_absence_type_filter,
        user_ids=current_table_user_ids,
    )
    table_sort_urls = _build_absence_table_sort_urls(
        department_name=department_name,
        filter_params=table_filter_params,
        current_sort_key=current_table_sort_key,
        current_sort_direction=current_table_sort_direction,
        default_sort_key="end",
        default_sort_direction="desc",
    )
    clear_table_params = {}
    if current_table_sort_key:
        clear_table_params["table_sort"] = current_table_sort_key
        clear_table_params["table_direction"] = current_table_sort_direction

    report_range = resolve_absence_report_date_range(range_key="this_month")

    return render_template(
        "staff_status/absences.html",
        department_name=department_name,
        users=users,
        absence_types=absence_types,
        duration_options=ABSENCE_DURATION_OPTIONS,
        past_absences=past_absences,
        active_tab="absences",
        current_table_absence_types=current_table_absence_types,
        current_table_user_ids=current_table_user_ids,
        current_table_date_range_key=table_range["key"],
        current_table_start_date=current_table_custom_start_date if table_range["key"] == "custom" else "",
        current_table_end_date=current_table_custom_end_date if table_range["key"] == "custom" else "",
        current_table_sort_key=current_table_sort_key,
        current_table_sort_direction=current_table_sort_direction,
        table_sort_labels=ABSENCE_TABLE_SORT_LABELS,
        table_sort_urls=table_sort_urls,
        active_table_filters=_build_absence_table_filter_labels(
            date_range=table_range,
            absence_type_filter=table_absence_type_filter,
            user_ids=current_table_user_ids,
            users=users,
        ),
        table_period_summary=_absence_range_summary(table_range),
        clear_table_filters_url=_build_absence_table_url(department_name, clear_table_params),
        table_date_range_options=table_date_range_options,
        report_date_range_options=report_date_range_options,
        report_default_date_range_key=report_range["key"],
        report_start_date=report_range["start_date_iso"],
        report_end_date=report_range["end_date_iso"],
        report_period_label=report_range["label"],
        report_period_helper=_absence_range_summary(report_range),
        accessible_department_count=len(accessible_departments),
        is_staff_status_admin=has_staff_status_admin(user_id),
        can_operate=can_operate,
    )


@bp.route("/absence-requests/<int:request_id>", methods=["GET", "POST"])
@login_required
def review_absence_request(request_id: int):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    request_record = get_pending_absence_request_by_id(request_id)
    if not request_record:
        abort(404)

    actor = get_user_by_id(user_id)
    if not actor:
        abort(403)

    if not _can_review_absence_request(user_id, actor, request_record):
        abort(403)

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        decision_note = (request.form.get("decision_note") or "").strip()

        try:
            if action == "approve":
                request_record = approve_pending_absence_request(
                    request_id=request_id,
                    reviewed_by_user_id=actor["id"],
                    reviewed_by_display_name=_actor_display_name(actor),
                    decision_note=decision_note,
                )
                publish_department_update(request_record["department_name"])
                flash("Absence request approved.", "success")
            elif action == "reject":
                request_record = reject_pending_absence_request(
                    request_id=request_id,
                    reviewed_by_user_id=actor["id"],
                    reviewed_by_display_name=_actor_display_name(actor),
                    decision_note=decision_note,
                )
                flash("Absence request rejected.", "success")
            else:
                flash("Choose whether to approve or reject the request.", "error")
        except (StaffStatusValidationError, PendingAbsenceRequestStateError) as exc:
            flash(str(exc), "error")

        return redirect(
            url_for(
                "staff_status.review_absence_request",
                request_id=request_id,
            )
        )

    return render_template(
        "staff_status/absence_request_review.html",
        request_record=request_record,
        active_tab="absences",
        can_review=True,
    )


@bp.route("/<department_name>/absences/export")
@login_required
def absences_export(department_name: str):
    user_id = session.get("user_id")
    if not user_id:
        abort(403)

    if not can_access_department(user_id, department_name):
        abort(403)

    absence_type_filter = (
        request.args.get("report_absence_type")
        or request.args.get("absence_type")
        or ""
    ).strip().lower()
    current_absence_types = [absence_type_filter] if absence_type_filter else []

    report_user_ids = [
        item.strip()
        for item in request.args.getlist("report_user_ids")
        if item.strip()
    ]
    legacy_user_ids = [
        item.strip()
        for item in request.args.getlist("user_ids")
        if item.strip()
    ]
    current_user_ids = report_user_ids if report_user_ids else legacy_user_ids

    timing = (request.args.get("timing") or "all").strip().lower()
    if timing not in {"upcoming", "past", "all"}:
        timing = "all"

    format_type = (request.args.get("format") or "csv").strip().lower()
    if format_type not in {"csv", "pdf"}:
        format_type = "csv"

    try:
        report_range = resolve_absence_report_date_range(
            range_key=request.args.get("report_date_range") or request.args.get("date_range") or "this_month",
            custom_start_date=request.args.get("report_start_date") or request.args.get("start_date"),
            custom_end_date=request.args.get("report_end_date") or request.args.get("end_date"),
        )
    except StaffStatusValidationError:
        abort(400)

    start_date = report_range["start_date_iso"]
    end_date = report_range["end_date_iso"]

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
