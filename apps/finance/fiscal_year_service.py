from datetime import datetime, timezone

from .db import get_connection
from .service import normalize_text


OPEN_STATUSES = {"planning", "active", "closing"}
VALID_STATUSES = {"planning", "active", "closing", "closed"}


START_CHECKLIST_TEMPLATE = [
    {
        "item_key": "create_fiscal_year",
        "label": "Create fiscal year",
        "description": "Fiscal year record has been created.",
        "is_required": 1,
        "is_skippable": 0,
        "auto_complete": True,
    },
    {
        "item_key": "upload_budget_definitions",
        "label": "Upload Budget Definitions",
        "description": "Upload the yearly eFinance Budget Unit definition export.",
        "is_required": 0,
        "is_skippable": 1,
        "auto_complete": False,
    },
    {
        "item_key": "review_active_budget_definitions",
        "label": "Review active Budget Definition set",
        "description": "Review the active uploaded Budget Definition set for this fiscal year.",
        "is_required": 1,
        "is_skippable": 0,
        "auto_complete": False,
    },
    {
        "item_key": "verify_building_aliases",
        "label": "Verify building aliases",
        "description": "Review building mappings and aliases, including legacy names.",
        "is_required": 1,
        "is_skippable": 0,
        "auto_complete": False,
    },
    {
        "item_key": "import_opening_transactions",
        "label": "Import current/opening transactions",
        "description": "Import current or opening transactions for this fiscal year.",
        "is_required": 0,
        "is_skippable": 1,
        "auto_complete": False,
    },
    {
        "item_key": "confirm_missing_budget_definitions",
        "label": "Confirm missing Budget Definitions",
        "description": "Review missing Budget Definition warnings. If skipped, warnings continue on future imports.",
        "is_required": 0,
        "is_skippable": 1,
        "auto_complete": False,
    },
]


CLOSE_CHECKLIST_TEMPLATE = [
    {
        "item_key": "review_unmatched_transactions",
        "label": "Review outstanding unmatched transactions",
        "description": "Review transactions that still need matching, promotion, or dismissal.",
        "is_required": 1,
        "is_skippable": 0,
        "auto_complete": False,
    },
    {
        "item_key": "resolve_missing_budget_definitions",
        "label": "Resolve missing Budget Definitions",
        "description": "Resolve missing definitions where possible. If skipped, warnings remain visible historically.",
        "is_required": 0,
        "is_skippable": 1,
        "auto_complete": False,
    },
    {
        "item_key": "review_export_year_end_data",
        "label": "Review / export year-end data",
        "description": "Choose exportable reports such as building, vendor, category, or overall transaction breakdowns.",
        "is_required": 0,
        "is_skippable": 1,
        "auto_complete": False,
    },
    {
        "item_key": "confirm_promoted_transactions_reviewed",
        "label": "Confirm promoted transactions reviewed",
        "description": "Confirm promoted transactions have been reviewed before closeout.",
        "is_required": 1,
        "is_skippable": 0,
        "auto_complete": False,
    },
    {
        "item_key": "mark_fiscal_year_closed",
        "label": "Mark fiscal year closed",
        "description": "Final closeout action. Closed fiscal years become read-only for setup workflows.",
        "is_required": 1,
        "is_skippable": 0,
        "auto_complete": False,
    },
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_fiscal_year_code(value: str | None) -> str:
    value = normalize_text(value).upper().replace(" ", "")

    if not value:
        return ""

    if value.startswith("FY"):
        suffix = value[2:]
    else:
        suffix = value

    if len(suffix) == 2 and suffix.isdigit():
        suffix = f"20{suffix}"

    if suffix.isdigit():
        return f"FY{suffix}"

    return value


def fiscal_year_aliases_for(code: str, year_number: int) -> list[str]:
    short_year = str(year_number)[-2:]
    return sorted(
        {
            code,
            code.replace("FY20", "FY"),
            str(year_number),
            f"FY{short_year}",
            f"Fiscal Year {year_number}",
        }
    )


def list_fiscal_years(include_closed: bool = True) -> list[dict]:
    where = ""
    params = []

    if not include_closed:
        where = "WHERE status != ?"
        params.append("closed")

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM finance_fiscal_years
            {where}
            ORDER BY year_number DESC
            """,
            params,
        ).fetchall()

    return [dict(row) for row in rows]


def get_fiscal_year(fiscal_year_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_years
            WHERE id = ?
            """,
            (fiscal_year_id,),
        ).fetchone()

    return dict(row) if row else None


def get_current_fiscal_year() -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_years
            WHERE is_current = 1
            ORDER BY year_number DESC
            LIMIT 1
            """
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
            SELECT *
            FROM finance_fiscal_years
            WHERE code = ?
               OR short_code = ?
               OR friendly_name = ?
               OR CAST(year_number AS TEXT) = ?
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
            JOIN finance_fiscal_years fy
                ON fy.id = a.fiscal_year_id
            WHERE UPPER(a.alias) = UPPER(?)
            LIMIT 1
            """,
            (raw_value,),
        ).fetchone()

    return dict(row) if row else None


def seed_fiscal_year_checklist(fiscal_year_id: int, created_by_user_id: int | None = None) -> None:
    now = utc_now_iso()

    checklist_sets = [
        ("start_year", START_CHECKLIST_TEMPLATE),
        ("close_year", CLOSE_CHECKLIST_TEMPLATE),
    ]

    with get_connection() as conn:
        for checklist_type, template in checklist_sets:
            for item in template:
                is_complete = 1 if item.get("auto_complete") else 0
                completed_at = now if is_complete else None
                completed_by = created_by_user_id if is_complete else None

                conn.execute(
                    """
                    INSERT OR IGNORE INTO finance_fiscal_year_checklist_items (
                        fiscal_year_id,
                        checklist_type,
                        item_key,
                        label,
                        description,
                        is_required,
                        is_skippable,
                        is_complete,
                        completed_at,
                        completed_by_user_id,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fiscal_year_id,
                        checklist_type,
                        item["item_key"],
                        item["label"],
                        item["description"],
                        item["is_required"],
                        item["is_skippable"],
                        is_complete,
                        completed_at,
                        completed_by,
                        now,
                        now,
                    ),
                )

        conn.commit()


def create_fiscal_year(
    *,
    year_number: int,
    start_date: str,
    end_date: str,
    friendly_name: str | None = None,
    make_current: bool = False,
    make_next: bool = False,
    created_by_user_id: int | None = None,
) -> int:
    now = utc_now_iso()

    code = f"FY{year_number}"
    short_code = f"FY{str(year_number)[-2:]}"
    friendly_name = normalize_text(friendly_name) or f"Fiscal Year {year_number}"

    if make_current and make_next:
        raise ValueError("A fiscal year cannot be both current and next.")

    with get_connection() as conn:
        active_open_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM finance_fiscal_years
            WHERE status IN ('planning', 'active', 'closing')
            """
        ).fetchone()["count"]

        existing = conn.execute(
            """
            SELECT id
            FROM finance_fiscal_years
            WHERE code = ?
            """,
            (code,),
        ).fetchone()

        if not existing and active_open_count >= 2:
            raise ValueError("Only two open fiscal years are allowed.")

        if make_current:
            conn.execute(
                """
                UPDATE finance_fiscal_years
                SET is_current = 0,
                    updated_at = ?
                """,
                (now,),
            )

        if make_next:
            conn.execute(
                """
                UPDATE finance_fiscal_years
                SET is_next = 0,
                    updated_at = ?
                """,
                (now,),
            )

        cursor = conn.execute(
            """
            INSERT INTO finance_fiscal_years (
                code,
                short_code,
                year_number,
                friendly_name,
                start_date,
                end_date,
                status,
                is_current,
                is_next,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'planning', ?, ?, ?, ?)
            """,
            (
                code,
                short_code,
                year_number,
                friendly_name,
                start_date,
                end_date,
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

    seed_fiscal_year_checklist(
        fiscal_year_id,
        created_by_user_id=created_by_user_id,
    )

    return fiscal_year_id


def update_fiscal_year_status(
    *,
    fiscal_year_id: int,
    status: str,
    is_current: bool = False,
    is_next: bool = False,
) -> None:
    status = normalize_text(status).lower()

    if status not in VALID_STATUSES:
        raise ValueError("Invalid fiscal year status.")

    if is_current and is_next:
        raise ValueError("A fiscal year cannot be both current and next.")

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

        if status != "closed":
            open_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM finance_fiscal_years
                WHERE status IN ('planning', 'active', 'closing')
                  AND id != ?
                """,
                (fiscal_year_id,),
            ).fetchone()["count"]

            if open_count >= 2:
                raise ValueError("Only two open fiscal years are allowed.")

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
            SET status = ?,
                is_current = ?,
                is_next = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                1 if is_current else 0,
                1 if is_next else 0,
                now,
                fiscal_year_id,
            ),
        )

        conn.commit()


def list_fiscal_year_checklist(fiscal_year_id: int, checklist_type: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_year_checklist_items
            WHERE fiscal_year_id = ?
              AND checklist_type = ?
            ORDER BY id
            """,
            (fiscal_year_id, checklist_type),
        ).fetchall()

    return [dict(row) for row in rows]


def set_checklist_item_state(
    *,
    checklist_item_id: int,
    complete: bool = False,
    skipped: bool = False,
    user_id: int | None = None,
) -> None:
    if complete and skipped:
        raise ValueError("Checklist item cannot be both complete and skipped.")

    now = utc_now_iso()

    with get_connection() as conn:
        item = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_year_checklist_items
            WHERE id = ?
            """,
            (checklist_item_id,),
        ).fetchone()

        if not item:
            raise ValueError("Checklist item not found.")

        if skipped and not item["is_skippable"]:
            raise ValueError("This checklist item cannot be skipped.")

        conn.execute(
            """
            UPDATE finance_fiscal_year_checklist_items
            SET is_complete = ?,
                is_skipped = ?,
                completed_at = ?,
                completed_by_user_id = ?,
                skipped_at = ?,
                skipped_by_user_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                1 if complete else 0,
                1 if skipped else 0,
                now if complete else None,
                user_id if complete else None,
                now if skipped else None,
                user_id if skipped else None,
                now,
                checklist_item_id,
            ),
        )

        conn.commit()


def get_fiscal_year_setup_summary() -> dict:
    years = list_fiscal_years(include_closed=True)

    return {
        "fiscal_years": years,
        "current_fiscal_year": next((item for item in years if item["is_current"]), None),
        "next_fiscal_year": next((item for item in years if item["is_next"]), None),
        "open_fiscal_year_count": len(
            [item for item in years if item["status"] in OPEN_STATUSES]
        ),
    }

def checklist_ready_for_workflow_completion(
    fiscal_year_id: int,
    checklist_type: str,
) -> bool:
    with get_connection() as conn:
        unresolved_required = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM finance_fiscal_year_checklist_items
            WHERE fiscal_year_id = ?
              AND checklist_type = ?
              AND is_required = 1
              AND is_complete = 0
            """,
            (fiscal_year_id, checklist_type),
        ).fetchone()["count"]

        unresolved_skippable = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM finance_fiscal_year_checklist_items
            WHERE fiscal_year_id = ?
              AND checklist_type = ?
              AND is_skippable = 1
              AND is_complete = 0
              AND is_skipped = 0
            """,
            (fiscal_year_id, checklist_type),
        ).fetchone()["count"]

    return unresolved_required == 0 and unresolved_skippable == 0


def get_fiscal_year_workflow_context() -> dict:
    years = list_fiscal_years(include_closed=True)

    current_year = next((item for item in years if item["is_current"]), None)
    next_year = next((item for item in years if item["is_next"]), None)

    return {
        "fiscal_years": years,
        "current_fiscal_year": current_year,
        "next_fiscal_year": next_year,
        "open_fiscal_year_count": len(
            [item for item in years if item["status"] in OPEN_STATUSES]
        ),
    }


def activate_fiscal_year_after_start_checklist(
    *,
    fiscal_year_id: int,
) -> None:
    if not checklist_ready_for_workflow_completion(fiscal_year_id, "start_year"):
        raise ValueError(
            "All required start checklist items must be completed, and all skippable items must be completed or skipped."
        )

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


def close_fiscal_year_after_close_checklist(
    *,
    fiscal_year_id: int,
) -> None:
    if not checklist_ready_for_workflow_completion(fiscal_year_id, "close_year"):
        raise ValueError(
            "All required close checklist items must be completed, and all skippable items must be completed or skipped."
        )

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
            SET status = 'closed',
                is_current = 0,
                is_next = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (now, fiscal_year_id),
        )

        next_year = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_years
            WHERE status = 'planning'
            ORDER BY year_number ASC
            LIMIT 1
            """
        ).fetchone()

        if next_year:
            conn.execute(
                """
                UPDATE finance_fiscal_years
                SET status = 'active',
                    is_current = 1,
                    is_next = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, next_year["id"]),
            )

        conn.commit()