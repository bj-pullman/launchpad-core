from __future__ import annotations

from datetime import datetime, timezone

from .db import get_connection
from .service import normalize_text


OPEN_STATUSES = {"planning", "active", "closing"}
VALID_STATUSES = {"planning", "active", "closing", "closed"}


START_CHECKLIST_TEMPLATE = [
    ("create_fiscal_year", "Create fiscal year", "Fiscal year record has been created.", 1, 0, True),
    ("upload_budget_definitions", "Upload Budget Definitions", "Upload the yearly eFinance Budget Unit definition export.", 0, 1, False),
    ("review_active_budget_definitions", "Review active Budget Definition set", "Review the active uploaded Budget Definition set for this fiscal year.", 1, 0, False),
    ("import_opening_transactions", "Import current/opening transactions", "Import current or opening transactions for this fiscal year.", 0, 1, False),
    ("confirm_missing_budget_definitions", "Confirm missing Budget Definitions", "Review missing Budget Definition warnings. If skipped, warnings continue on future imports.", 0, 1, False),
]

CLOSE_CHECKLIST_TEMPLATE = [
    ("review_unmatched_transactions", "Review outstanding unmatched transactions", "Review transactions that still need matching, promotion, or dismissal.", 1, 0, False),
    ("resolve_missing_budget_definitions", "Resolve missing Budget Definitions", "Resolve missing definitions where possible. If skipped, warnings remain visible historically.", 0, 1, False),
    ("review_export_year_end_data", "Review / export year-end data", "Choose exportable reports such as building, vendor, category, or overall transaction breakdowns.", 0, 1, False),
    ("confirm_promoted_transactions_reviewed", "Confirm promoted transactions reviewed", "Confirm promoted transactions have been reviewed before closeout.", 1, 0, False),
    ("mark_fiscal_year_closed", "Mark fiscal year closed", "Final closeout action. Closed fiscal years become read-only for setup workflows.", 1, 0, False),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_fiscal_year_code(value: str | None) -> str:
    value = (normalize_text(value) or "").upper().replace(" ", "")
    if not value:
        return ""
    suffix = value[2:] if value.startswith("FY") else value
    if len(suffix) == 2 and suffix.isdigit():
        suffix = f"20{suffix}"
    return f"FY{suffix}" if suffix.isdigit() else value


def fiscal_year_aliases_for(code: str, year_number: int) -> list[str]:
    short_year = str(year_number)[-2:]
    return sorted({code, code.replace("FY20", "FY"), str(year_number), f"FY{short_year}", f"Fiscal Year {year_number}"})


def _role_limited_years(years: list[dict]) -> list[dict]:
    selected: dict[int, dict] = {}
    for item in years:
        if item.get("is_current") or item.get("is_next") or item.get("status") in OPEN_STATUSES:
            selected[item["id"]] = item
    previous_year = next((item for item in years if item.get("status") == "closed"), None)
    if previous_year:
        selected[previous_year["id"]] = previous_year
    return sorted(selected.values(), key=lambda item: item["year_number"], reverse=True)


def list_fiscal_years(department_name: str, include_closed: bool = True) -> list[dict]:
    with get_connection() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM finance_fiscal_years
                WHERE department_name = ?
                ORDER BY year_number DESC
                """,
                (department_name,),
            ).fetchall()
        ]

    if not include_closed:
        return [item for item in rows if item["status"] != "closed"]

    return _role_limited_years(rows)


def get_fiscal_year(fiscal_year_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM finance_fiscal_years WHERE id = ?", (fiscal_year_id,)).fetchone()
    return dict(row) if row else None


def get_current_fiscal_year() -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM finance_fiscal_years WHERE is_current = 1 ORDER BY year_number DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def resolve_fiscal_year(value: str | None) -> dict | None:
    raw_value = normalize_text(value)
    code = normalize_fiscal_year_code(raw_value)
    if not raw_value:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM finance_fiscal_years
            WHERE code = ? OR short_code = ? OR friendly_name = ? OR CAST(year_number AS TEXT) = ?
            LIMIT 1
            """,
            (code, raw_value, raw_value, raw_value),
        ).fetchone()
        if row:
            return dict(row)
        row = conn.execute(
            """
            SELECT fy.*
            FROM finance_fiscal_year_aliases a
            JOIN finance_fiscal_years fy ON fy.id = a.fiscal_year_id
            WHERE UPPER(a.alias) = UPPER(?)
            LIMIT 1
            """,
            (raw_value,),
        ).fetchone()
    return dict(row) if row else None


def seed_fiscal_year_checklist(fiscal_year_id: int, created_by_user_id: int | None = None) -> None:
    now = utc_now_iso()
    checklist_sets = (("start_year", START_CHECKLIST_TEMPLATE), ("close_year", CLOSE_CHECKLIST_TEMPLATE))
    with get_connection() as conn:
        for checklist_type, template in checklist_sets:
            for item_key, label, description, is_required, is_skippable, auto_complete in template:
                is_complete = 1 if auto_complete else 0
                conn.execute(
                    """
                    INSERT OR IGNORE INTO finance_fiscal_year_checklist_items (
                        fiscal_year_id, checklist_type, item_key, label, description,
                        is_required, is_skippable, is_complete, completed_at,
                        completed_by_user_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fiscal_year_id, checklist_type, item_key, label, description,
                        is_required, is_skippable, is_complete,
                        now if is_complete else None,
                        created_by_user_id if is_complete else None,
                        now, now,
                    ),
                )
        conn.commit()

def fiscal_year_dates_overlap(
    *,
    department_name: str,
    start_date: str,
    end_date: str,
    exclude_fiscal_year_id: int | None = None,
) -> bool:
    with get_connection() as conn:
        params = [department_name, end_date, start_date]

        exclude_sql = ""
        if exclude_fiscal_year_id:
            exclude_sql = "AND id != ?"
            params.append(exclude_fiscal_year_id)

        row = conn.execute(
            f"""
            SELECT id
            FROM finance_fiscal_years
            WHERE department_name = ?
              AND date(start_date) <= date(?)
              AND date(end_date) >= date(?)
              {exclude_sql}
            LIMIT 1
            """,
            params,
        ).fetchone()

    return row is not None


def create_fiscal_year(
    *,
    department_name: str,
    year_number: int,
    start_date: str,
    end_date: str,
    friendly_name: str | None = None,
    adopted_budget: str | None = None,
    make_previous: bool = False,
    make_current: bool = False,
    make_next: bool = False,
    created_by_user_id: int | None = None,
) -> int:
    role_count = sum([make_previous, make_current, make_next])
    if role_count > 1:
        raise ValueError("A fiscal year can only have one role: Previous, Current, or Next.")

    department_name = normalize_text(department_name)
    if not department_name:
        raise ValueError("Department is required.")

    if not year_number:
        raise ValueError("Fiscal year is required.")

    if not start_date or not end_date:
        raise ValueError("Start date and end date are required.")

    if fiscal_year_dates_overlap(
        department_name=department_name,
        start_date=start_date,
        end_date=end_date,
    ):
        raise ValueError("Fiscal year dates overlap with an existing fiscal year for this department.")

    now = utc_now_iso()
    code = f"FY{year_number}"
    short_code = f"FY{str(year_number)[-2:]}"
    friendly_name = normalize_text(friendly_name) or f"Fiscal Year {year_number}"
    adopted_budget = normalize_text(adopted_budget) or "0.00"

    with get_connection() as conn:
        open_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM finance_fiscal_years
            WHERE department_name = ?
              AND status IN ('planning', 'active', 'closing')
            """,
            (department_name,),
        ).fetchone()["count"]

        existing = conn.execute(
            """
            SELECT id
            FROM finance_fiscal_years
            WHERE department_name = ?
              AND code = ?
            """,
            (department_name, code),
        ).fetchone()

        if existing:
            raise ValueError(f"{code} already exists for {department_name}.")

        if open_count >= 3:
            raise ValueError("Only three open fiscal years are allowed per department: Previous, Current, and Next.")

        if make_previous:
            conn.execute(
                """
                UPDATE finance_fiscal_years
                SET is_previous = 0,
                    updated_at = ?
                WHERE department_name = ?
                """,
                (now, department_name),
            )

        if make_current:
            conn.execute(
                """
                UPDATE finance_fiscal_years
                SET is_current = 0,
                    updated_at = ?
                WHERE department_name = ?
                """,
                (now, department_name),
            )

        if make_next:
            conn.execute(
                """
                UPDATE finance_fiscal_years
                SET is_next = 0,
                    updated_at = ?
                WHERE department_name = ?
                """,
                (now, department_name),
            )

        cursor = conn.execute(
            """
            INSERT INTO finance_fiscal_years (
                department_name,
                code,
                short_code,
                year_number,
                friendly_name,
                start_date,
                end_date,
                adopted_budget,
                status,
                is_previous,
                is_current,
                is_next,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planning', ?, ?, ?, ?, ?)
            """,
            (
                department_name,
                code,
                short_code,
                year_number,
                friendly_name,
                start_date,
                end_date,
                adopted_budget,
                1 if make_previous else 0,
                1 if make_current else 0,
                1 if make_next else 0,
                now,
                now,
            ),
        )

        fiscal_year_id = cursor.lastrowid

        for alias in fiscal_year_aliases_for(code, year_number):
            conn.execute(
                """
                INSERT OR IGNORE INTO finance_fiscal_year_aliases (
                    fiscal_year_id,
                    alias,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (fiscal_year_id, alias, now, now),
            )

        conn.commit()

    return fiscal_year_id


def update_fiscal_year_status(*, fiscal_year_id: int, status: str, is_current: bool = False, is_next: bool = False) -> None:
    status = (normalize_text(status) or "").lower()
    if status not in VALID_STATUSES:
        raise ValueError("Invalid fiscal year status.")
    if is_current and is_next:
        raise ValueError("A fiscal year cannot be both current and next.")
    now = utc_now_iso()
    with get_connection() as conn:
        fiscal_year = conn.execute("SELECT * FROM finance_fiscal_years WHERE id = ?", (fiscal_year_id,)).fetchone()
        if not fiscal_year:
            raise ValueError("Fiscal year not found.")
        if status != "closed":
            open_count = conn.execute("SELECT COUNT(*) AS count FROM finance_fiscal_years WHERE status IN ('planning','active','closing') AND id != ?", (fiscal_year_id,)).fetchone()["count"]
            if open_count >= 3:
                raise ValueError("Only three open fiscal years are allowed: previous, current, and next.")
        if is_current:
            conn.execute("UPDATE finance_fiscal_years SET is_current = 0, updated_at = ? WHERE id != ?", (now, fiscal_year_id))
        if is_next:
            conn.execute("UPDATE finance_fiscal_years SET is_next = 0, updated_at = ? WHERE id != ?", (now, fiscal_year_id))
        conn.execute(
            "UPDATE finance_fiscal_years SET status = ?, is_current = ?, is_next = ?, updated_at = ? WHERE id = ?",
            (status, 1 if is_current else 0, 1 if is_next else 0, now, fiscal_year_id),
        )
        conn.commit()


def list_fiscal_year_checklist(fiscal_year_id: int, checklist_type: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM finance_fiscal_year_checklist_items WHERE fiscal_year_id = ? AND checklist_type = ? ORDER BY id",
            (fiscal_year_id, checklist_type),
        ).fetchall()
    return [dict(row) for row in rows]


def set_checklist_item_state(*, checklist_item_id: int, complete: bool = False, skipped: bool = False, user_id: int | None = None) -> None:
    if complete and skipped:
        raise ValueError("Checklist item cannot be both complete and skipped.")
    now = utc_now_iso()
    with get_connection() as conn:
        item = conn.execute("SELECT * FROM finance_fiscal_year_checklist_items WHERE id = ?", (checklist_item_id,)).fetchone()
        if not item:
            raise ValueError("Checklist item not found.")
        if skipped and not item["is_skippable"]:
            raise ValueError("This checklist item cannot be skipped.")
        conn.execute(
            """
            UPDATE finance_fiscal_year_checklist_items
            SET is_complete = ?, is_skipped = ?, completed_at = ?, completed_by_user_id = ?,
                skipped_at = ?, skipped_by_user_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (1 if complete else 0, 1 if skipped else 0, now if complete else None, user_id if complete else None, now if skipped else None, user_id if skipped else None, now, checklist_item_id),
        )
        conn.commit()


def get_fiscal_year_setup_summary(department_name: str) -> dict:
    years = list_fiscal_years(department_name=department_name, include_closed=True)

    return {
        "fiscal_years": years,
        "current_fiscal_year": next((item for item in years if item["is_current"]), None),
        "next_fiscal_year": next((item for item in years if item["is_next"]), None),
        "open_fiscal_year_count": len([item for item in years if item["status"] in OPEN_STATUSES]),
    }


def checklist_ready_for_workflow_completion(fiscal_year_id: int, checklist_type: str) -> bool:
    with get_connection() as conn:
        required = conn.execute(
            "SELECT COUNT(*) AS count FROM finance_fiscal_year_checklist_items WHERE fiscal_year_id = ? AND checklist_type = ? AND is_required = 1 AND is_complete = 0",
            (fiscal_year_id, checklist_type),
        ).fetchone()["count"]
        skippable = conn.execute(
            "SELECT COUNT(*) AS count FROM finance_fiscal_year_checklist_items WHERE fiscal_year_id = ? AND checklist_type = ? AND is_skippable = 1 AND is_complete = 0 AND is_skipped = 0",
            (fiscal_year_id, checklist_type),
        ).fetchone()["count"]
    return required == 0 and skippable == 0


def get_fiscal_year_workflow_context(department_name: str) -> dict:
    years = list_fiscal_years(department_name=department_name, include_closed=True)

    current_year = next((item for item in years if item.get("is_current")), None)
    previous_year = next((item for item in years if item.get("is_previous")), None)
    next_year = next((item for item in years if item.get("is_next")), None)

    stale_open_previous_years = []

    if current_year:
        stale_open_previous_years = [
            item
            for item in years
            if int(item["year_number"]) < int(current_year["year_number"]) - 1
            and item.get("status") != "closed"
        ]

    return {
        "fiscal_years": years,
        "previous_fiscal_year": previous_year,
        "current_fiscal_year": current_year,
        "next_fiscal_year": next_year,
        "stale_open_previous_years": stale_open_previous_years,
        "open_fiscal_year_count": len(
            [item for item in years if item["status"] in OPEN_STATUSES]
        ),
    }


def activate_fiscal_year_after_start_checklist(*, fiscal_year_id: int) -> None:
    now = utc_now_iso()

    with get_connection() as conn:
        fiscal_year = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_years
            WHERE id = ?
            """,
            (fiscal_year_id,),
        ).fetchone()

        if not fiscal_year:
            raise ValueError("Fiscal year not found.")

        conn.execute(
            """
            UPDATE finance_fiscal_years
            SET is_current = 0,
                updated_at = ?
            """,
            (now,),
        )

        conn.execute(
            """
            UPDATE finance_fiscal_years
            SET status = 'active',
                is_current = 1,
                is_next = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (now, fiscal_year_id),
        )

        conn.commit()


def close_fiscal_year_after_close_checklist(*, fiscal_year_id: int) -> None:
    if not checklist_ready_for_workflow_completion(fiscal_year_id, "close_year"):
        raise ValueError("All required close checklist items must be completed, and all skippable items must be completed or skipped.")
    now = utc_now_iso()
    with get_connection() as conn:
        fiscal_year = conn.execute("SELECT * FROM finance_fiscal_years WHERE id = ?", (fiscal_year_id,)).fetchone()
        if not fiscal_year:
            raise ValueError("Fiscal year not found.")
        conn.execute("UPDATE finance_fiscal_years SET status = 'closed', is_current = 0, is_next = 0, updated_at = ? WHERE id = ?", (now, fiscal_year_id))
        next_year = conn.execute("SELECT * FROM finance_fiscal_years WHERE status = 'planning' ORDER BY year_number ASC LIMIT 1").fetchone()
        if next_year:
            conn.execute("UPDATE finance_fiscal_years SET status = 'active', is_current = 1, is_next = 0, updated_at = ? WHERE id = ?", (now, next_year["id"]))
        conn.commit()

def update_fiscal_year(
    *,
    fiscal_year_id: int,
    year_number: int,
    friendly_name: str | None,
    start_date: str,
    end_date: str,
    adopted_budget: str | None = None,
    status: str,
    is_previous: bool = False,
    is_current: bool = False,
    is_next: bool = False,
) -> None:
    status = (normalize_text(status) or "").lower()

    if status not in VALID_STATUSES:
        raise ValueError("Invalid fiscal year status.")

    role_count = sum([is_previous, is_current, is_next])
    if role_count > 1:
        raise ValueError("A fiscal year can only have one role: Previous, Current, or Next.")

    if not year_number:
        raise ValueError("Fiscal year is required.")

    if not start_date or not end_date:
        raise ValueError("Start date and end date are required.")

    if fiscal_year_dates_overlap(
        start_date=start_date,
        end_date=end_date,
        exclude_fiscal_year_id=fiscal_year_id,
    ):
        raise ValueError("Fiscal year dates overlap with an existing fiscal year.")

    now = utc_now_iso()
    code = f"FY{year_number}"
    short_code = f"FY{str(year_number)[-2:]}"
    friendly_name = normalize_text(friendly_name) or f"Fiscal Year {year_number}"
    adopted_budget = normalize_text(adopted_budget) or "0.00"

    with get_connection() as conn:
        fiscal_year = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_years
            WHERE id = ?
            """,
            (fiscal_year_id,),
        ).fetchone()

        if not fiscal_year:
            raise ValueError("Fiscal year not found.")

        duplicate = conn.execute(
            """
            SELECT id
            FROM finance_fiscal_years
            WHERE code = ?
              AND id != ?
            """,
            (code, fiscal_year_id),
        ).fetchone()

        if duplicate:
            raise ValueError(f"{code} already exists.")

        if is_previous:
            conn.execute(
                """
                UPDATE finance_fiscal_years
                SET is_previous = 0,
                    updated_at = ?
                WHERE id != ?
                """,
                (now, fiscal_year_id),
            )

        if is_current:
            conn.execute(
                """
                UPDATE finance_fiscal_years
                SET is_current = 0,
                    updated_at = ?
                WHERE id != ?
                """,
                (now, fiscal_year_id),
            )

        if is_next:
            conn.execute(
                """
                UPDATE finance_fiscal_years
                SET is_next = 0,
                    updated_at = ?
                WHERE id != ?
                """,
                (now, fiscal_year_id),
            )

        conn.execute(
            """
            UPDATE finance_fiscal_years
            SET code = ?,
                short_code = ?,
                year_number = ?,
                friendly_name = ?,
                start_date = ?,
                end_date = ?,
                adopted_budget = ?,
                status = ?,
                is_previous = ?,
                is_current = ?,
                is_next = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                code,
                short_code,
                year_number,
                friendly_name,
                start_date,
                end_date,
                adopted_budget,
                status,
                1 if is_previous else 0,
                1 if is_current else 0,
                1 if is_next else 0,
                now,
                fiscal_year_id,
            ),
        )

        conn.execute(
            """
            DELETE FROM finance_fiscal_year_aliases
            WHERE fiscal_year_id = ?
            """,
            (fiscal_year_id,),
        )

        for alias in fiscal_year_aliases_for(code, year_number):
            conn.execute(
                """
                INSERT OR IGNORE INTO finance_fiscal_year_aliases (
                    fiscal_year_id,
                    alias,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (fiscal_year_id, alias, now, now),
            )

        conn.commit()