from __future__ import annotations

from .db import get_connection
from .fiscal_year_service import checklist_ready_for_workflow_completion, utc_now_iso


def activate_fiscal_year_after_start_checklist(*, fiscal_year_id: int) -> None:
    if not checklist_ready_for_workflow_completion(fiscal_year_id, "start_year"):
        raise ValueError(
            "All required start checklist items must be completed, and all skippable items must be completed or skipped."
        )

    now = utc_now_iso()
    with get_connection() as conn:
        fiscal_year = conn.execute(
            "SELECT * FROM finance_fiscal_years WHERE id = ?",
            (fiscal_year_id,),
        ).fetchone()
        if not fiscal_year:
            raise ValueError("Fiscal year not found.")

        conn.execute(
            """
            UPDATE finance_fiscal_years
            SET is_current = 0,
                updated_at = ?
            WHERE id != ?
            """,
            (now, fiscal_year_id),
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
        raise ValueError(
            "All required close checklist items must be completed, and all skippable items must be completed or skipped."
        )

    now = utc_now_iso()
    with get_connection() as conn:
        fiscal_year = conn.execute(
            "SELECT * FROM finance_fiscal_years WHERE id = ?",
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
