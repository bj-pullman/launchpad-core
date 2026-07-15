from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
import re
from difflib import SequenceMatcher

from calendar import monthrange
from datetime import date, datetime, timezone

from .db import get_connection


ACTIVE_RENEWAL_STATUSES = {
    "active",
    "planned",
    "under_review",
    "paused",
}

VALID_RENEWAL_STATUSES = {
    "active",
    "planned",
    "under_review",
    "paused",
    "discontinued",
    "replaced",
}

VALID_CYCLE_STATUSES = {
    "awaiting_activity",
    "activity_found",
    "needs_review",
    "partially_reconciled",
    "reconciled",
    "renewed",
    "not_renewed",
    "cancelled",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def normalize_money(value: Any) -> str | None:
    value = normalize_text(value)
    if value is None:
        return None

    cleaned = (
        value.replace("$", "")
        .replace(",", "")
        .replace("(", "-")
        .replace(")", "")
        .strip()
    )

    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid money value: {value}")

    return str(amount.quantize(Decimal("0.01")))


def money_decimal(value: Any) -> Decimal:
    value = normalize_text(value)
    if value is None:
        return Decimal("0.00")

    cleaned = (
        value.replace("$", "")
        .replace(",", "")
        .replace("(", "-")
        .replace(")", "")
        .strip()
    )

    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def normalize_status(value: Any, allowed: set[str], default: str) -> str:
    status = (normalize_text(value) or default).lower().replace(" ", "_")

    if status not in allowed:
        raise ValueError(f"Invalid status: {status}")

    return status


def list_fiscal_year_options() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                code,
                short_code,
                year_number,
                friendly_name,
                start_date,
                end_date,
                status,
                is_current,
                is_next,
                COALESCE(is_previous, 0) AS is_previous
            FROM finance_fiscal_years
            ORDER BY year_number DESC, start_date DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_default_fiscal_year() -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                code,
                short_code,
                year_number,
                friendly_name,
                start_date,
                end_date,
                status,
                is_current,
                is_next,
                COALESCE(is_previous, 0) AS is_previous
            FROM finance_fiscal_years
            ORDER BY
                is_current DESC,
                is_next DESC,
                year_number DESC,
                start_date DESC
            LIMIT 1
            """
        ).fetchone()

    return dict(row) if row else None


def get_fiscal_year_by_id(fiscal_year_id: int | None) -> dict | None:
    if not fiscal_year_id:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                code,
                short_code,
                year_number,
                friendly_name,
                start_date,
                end_date,
                status,
                is_current,
                is_next,
                COALESCE(is_previous, 0) AS is_previous
            FROM finance_fiscal_years
            WHERE id = ?
            """,
            (fiscal_year_id,),
        ).fetchone()

    return dict(row) if row else None


def get_fiscal_year_label(fiscal_year: dict | None) -> str:
    if not fiscal_year:
        return "Unassigned"

    return (
        normalize_text(fiscal_year.get("friendly_name"))
        or normalize_text(fiscal_year.get("short_code"))
        or normalize_text(fiscal_year.get("code"))
        or str(fiscal_year["year_number"])
    )


def add_renewal_history(
    *,
    renewal_id: int,
    event_type: str,
    summary: str | None = None,
    renewal_cycle_id: int | None = None,
    source_type: str = "manual",
    confidence_score: float | None = None,
    changed_by_user_id: int | None = None,
) -> int:
    now = utc_now_iso()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO finance_renewal_history (
                renewal_id,
                renewal_cycle_id,
                event_type,
                summary,
                source_type,
                confidence_score,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                renewal_id,
                renewal_cycle_id,
                normalize_text(event_type) or "updated",
                normalize_text(summary),
                normalize_text(source_type) or "manual",
                confidence_score,
                changed_by_user_id,
                now,
            ),
        )
        conn.commit()

    return cursor.lastrowid


def create_renewal(
    *,
    renewal_name: str,
    department_name: str,
    primary_vendor_id: int | None = None,
    category_id: int | None = None,
    purpose: str | None = None,
    status: str = "active",
    expected_renewal_hint: bool = False,
    default_notification_days: int = 30,
    notification_recipients: str | None = None,
    notes: str | None = None,
    fiscal_year_id: int | None = None,
    fiscal_year_label: str | None = None,
    cycle_status: str = "awaiting_activity",
    renewal_date: str | None = None,
    service_start_date: str | None = None,
    service_end_date: str | None = None,
    expected_cost: str | None = None,
    created_by_user_id: int | None = None,
) -> tuple[int, int | None]:
    renewal_name = normalize_text(renewal_name)
    department_name = normalize_text(department_name)

    if not renewal_name:
        raise ValueError("Renewal name is required.")

    if not department_name:
        raise ValueError("Department name is required.")

    status = normalize_status(status, VALID_RENEWAL_STATUSES, "active")
    cycle_status = normalize_status(
        cycle_status,
        VALID_CYCLE_STATUSES,
        "awaiting_activity",
    )

    try:
        default_notification_days = int(default_notification_days or 30)
    except (TypeError, ValueError):
        default_notification_days = 30

    default_notification_days = max(default_notification_days, 0)
    expected_cost = normalize_money(expected_cost)

    fiscal_year = get_fiscal_year_by_id(fiscal_year_id)

    if fiscal_year:
        fiscal_year_label = get_fiscal_year_label(fiscal_year)
    else:
        fiscal_year_label = normalize_text(fiscal_year_label)

    should_create_initial_cycle = any(
        [
            fiscal_year_id,
            fiscal_year_label,
            normalize_text(renewal_date),
            normalize_text(service_start_date),
            normalize_text(service_end_date),
            expected_cost,
        ]
    )

    now = utc_now_iso()

    with get_connection() as conn:
        duplicate = conn.execute(
            """
            SELECT id
            FROM finance_renewals
            WHERE department_name = ?
              AND LOWER(TRIM(renewal_name)) = LOWER(TRIM(?))
              AND status NOT IN ('discontinued', 'replaced')
            LIMIT 1
            """,
            (department_name, renewal_name),
        ).fetchone()

        if duplicate:
            raise ValueError(
                "An active Renewal with this name already exists for the department."
            )

        cursor = conn.execute(
            """
            INSERT INTO finance_renewals (
                renewal_name,
                department_name,
                primary_vendor_id,
                category_id,
                purpose,
                status,
                expected_renewal_hint,
                default_notification_days,
                notification_recipients,
                notes,
                created_by_user_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                renewal_name,
                department_name,
                primary_vendor_id,
                category_id,
                normalize_text(purpose),
                status,
                1 if expected_renewal_hint else 0,
                default_notification_days,
                normalize_text(notification_recipients),
                normalize_text(notes),
                created_by_user_id,
                now,
                now,
            ),
        )

        renewal_id = cursor.lastrowid

        cycle_id = None

        if should_create_initial_cycle:
            if not fiscal_year_label:
                raise ValueError(
                    "Select a fiscal year or enter a custom fiscal-year label "
                    "when creating an initial annual cycle."
                )

            cycle_cursor = conn.execute(
                """
                INSERT INTO finance_renewal_cycles (
                    renewal_id,
                    fiscal_year_id,
                    fiscal_year_label,
                    cycle_status,
                    renewal_date,
                    service_start_date,
                    service_end_date,
                    expected_cost,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    renewal_id,
                    fiscal_year_id,
                    fiscal_year_label,
                    cycle_status,
                    normalize_text(renewal_date),
                    normalize_text(service_start_date),
                    normalize_text(service_end_date),
                    expected_cost,
                    now,
                    now,
                ),
            )

            cycle_id = cycle_cursor.lastrowid

        history_summary = "Renewal created."

        if cycle_id:
            history_summary = (
                f"Renewal created with initial cycle {fiscal_year_label}."
            )

        conn.execute(
            """
            INSERT INTO finance_renewal_history (
                renewal_id,
                renewal_cycle_id,
                event_type,
                summary,
                source_type,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, ?, 'created', ?, 'manual', ?, ?)
            """,
            (
                renewal_id,
                cycle_id,
                history_summary,
                created_by_user_id,
                now,
            ),
        )

        conn.commit()

    return renewal_id, cycle_id


def create_renewal_cycle(
    *,
    renewal_id: int,
    fiscal_year_id: int | None = None,
    fiscal_year_label: str | None = None,
    cycle_status: str = "awaiting_activity",
    renewal_date: str | None = None,
    service_start_date: str | None = None,
    service_end_date: str | None = None,
    expected_cost: str | None = None,
    created_by_user_id: int | None = None,
) -> int:
    renewal = get_renewal_by_id(renewal_id)
    if not renewal:
        raise ValueError("Renewal not found.")

    cycle_status = normalize_status(
        cycle_status,
        VALID_CYCLE_STATUSES,
        "awaiting_activity",
    )

    fiscal_year = get_fiscal_year_by_id(fiscal_year_id)

    if fiscal_year:
        fiscal_year_label = get_fiscal_year_label(fiscal_year)
    else:
        fiscal_year_label = normalize_text(fiscal_year_label)

    if not fiscal_year_label:
        raise ValueError("Fiscal year is required.")

    expected_cost = normalize_money(expected_cost)
    now = utc_now_iso()

    with get_connection() as conn:
        duplicate = conn.execute(
            """
            SELECT id
            FROM finance_renewal_cycles
            WHERE renewal_id = ?
              AND LOWER(TRIM(fiscal_year_label)) = LOWER(TRIM(?))
            LIMIT 1
            """,
            (renewal_id, fiscal_year_label),
        ).fetchone()

        if duplicate:
            raise ValueError(
                f"A {fiscal_year_label} cycle already exists for this Renewal."
            )

        cursor = conn.execute(
            """
            INSERT INTO finance_renewal_cycles (
                renewal_id,
                fiscal_year_id,
                fiscal_year_label,
                cycle_status,
                renewal_date,
                service_start_date,
                service_end_date,
                expected_cost,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                renewal_id,
                fiscal_year_id,
                fiscal_year_label,
                cycle_status,
                normalize_text(renewal_date),
                normalize_text(service_start_date),
                normalize_text(service_end_date),
                expected_cost,
                now,
                now,
            ),
        )
        cycle_id = cursor.lastrowid
        conn.commit()

    add_renewal_history(
        renewal_id=renewal_id,
        renewal_cycle_id=cycle_id,
        event_type="cycle_created",
        summary=f"Renewal cycle created for {fiscal_year_label}.",
        changed_by_user_id=created_by_user_id,
    )

    return cycle_id


def get_cycle_actual_cost(conn, cycle_id: int) -> Decimal:
    record_total_row = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN l.counts_toward_cost = 1
                        THEN CAST(COALESCE(r.cost, '0') AS REAL)
                        ELSE 0
                    END
                ),
                0
            ) AS total
        FROM finance_renewal_record_links l
        INNER JOIN finance_records r
            ON r.id = l.finance_record_id
        WHERE l.renewal_cycle_id = ?
          AND r.status NOT IN ('deleted')
        """,
        (cycle_id,),
    ).fetchone()

    transaction_total_row = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN l.counts_toward_cost = 1
                        THEN
                            CAST(COALESCE(t.expenditure_amount, '0') AS REAL)
                            +
                            CAST(COALESCE(t.encumbrance_amount, '0') AS REAL)
                        ELSE 0
                    END
                ),
                0
            ) AS total
        FROM finance_renewal_transaction_links l
        INNER JOIN finance_transactions t
            ON t.id = l.finance_transaction_id
        WHERE l.renewal_cycle_id = ?
        """,
        (cycle_id,),
    ).fetchone()

    record_total = Decimal(str(record_total_row["total"] or 0))
    transaction_total = Decimal(str(transaction_total_row["total"] or 0))

    return record_total + transaction_total


def get_renewal_cycles(renewal_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                rc.*,
                fy.code AS fiscal_year_code,
                fy.friendly_name AS fiscal_year_friendly_name
            FROM finance_renewal_cycles rc
            LEFT JOIN finance_fiscal_years fy
                ON fy.id = rc.fiscal_year_id
            WHERE rc.renewal_id = ?
            ORDER BY
                COALESCE(fy.year_number, 0) DESC,
                rc.service_start_date DESC,
                rc.id DESC
            """,
            (renewal_id,),
        ).fetchall()

        cycles = []

        for row in rows:
            cycle = dict(row)
            actual_cost = get_cycle_actual_cost(conn, cycle["id"])

            cycle["actual_cost_decimal"] = actual_cost
            cycle["actual_cost"] = str(actual_cost.quantize(Decimal("0.01")))
            cycle["display_cost"] = (
                cycle["actual_cost"]
                if actual_cost != Decimal("0.00")
                else cycle.get("expected_cost")
            )
            cycles.append(cycle)

    previous_cost: Decimal | None = None

    for cycle in reversed(cycles):
        current_cost = money_decimal(cycle.get("display_cost"))

        cycle["cost_change_amount"] = None
        cycle["cost_change_percent"] = None

        if previous_cost is not None:
            change = current_cost - previous_cost
            cycle["cost_change_amount"] = str(
                change.quantize(Decimal("0.01"))
            )

            if previous_cost != Decimal("0.00"):
                percent = (change / previous_cost) * Decimal("100")
                cycle["cost_change_percent"] = float(
                    percent.quantize(Decimal("0.1"))
                )

        if current_cost != Decimal("0.00"):
            previous_cost = current_cost

    return cycles


def calculate_renewal_metrics(cycles: list[dict]) -> dict:
    tracked_cycles = [
        cycle
        for cycle in cycles
        if money_decimal(cycle.get("display_cost")) != Decimal("0.00")
    ]

    current_cycle = cycles[0] if cycles else None
    current_cost = (
        money_decimal(current_cycle.get("display_cost"))
        if current_cycle
        else Decimal("0.00")
    )

    tracked_cost = sum(
        (
            money_decimal(cycle.get("display_cost"))
            for cycle in tracked_cycles
        ),
        Decimal("0.00"),
    )

    return {
        "current_cost": str(current_cost.quantize(Decimal("0.01"))),
        "cost_change_amount": (
            current_cycle.get("cost_change_amount")
            if current_cycle
            else None
        ),
        "cost_change_percent": (
            current_cycle.get("cost_change_percent")
            if current_cycle
            else None
        ),
        "years_tracked": len(tracked_cycles),
        "tracked_cost": str(tracked_cost.quantize(Decimal("0.01"))),
        "current_cycle": current_cycle,
    }


def get_renewal_by_id(renewal_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                r.*,
                v.vendor_name,
                v.friendly_name AS vendor_friendly_name,
                c.category_name
            FROM finance_renewals r
            LEFT JOIN finance_vendors v
                ON v.id = r.primary_vendor_id
            LEFT JOIN finance_categories c
                ON c.id = r.category_id
            WHERE r.id = ?
            """,
            (renewal_id,),
        ).fetchone()

    if not row:
        return None

    renewal = dict(row)
    cycles = get_renewal_cycles(renewal_id)

    renewal["cycles"] = cycles
    renewal["metrics"] = calculate_renewal_metrics(cycles)
    renewal["department_breakdown"] = calculate_department_breakdown(
        cycles
    )

    for cycle in renewal["cycles"]:
        cycle["activity"] = get_linked_activity_for_cycle(
            cycle["id"]
        )

    return renewal


def list_renewals_for_department(
    department_name: str,
    *,
    q: str | None = None,
    status: str | None = None,
) -> list[dict]:
    department_name = normalize_text(department_name)
    q = normalize_text(q)
    status = normalize_text(status)

    if not department_name:
        return []

    where = ["r.department_name = ?"]
    params: list[Any] = [department_name]

    if q:
        where.append(
            """
            (
                LOWER(COALESCE(r.renewal_name, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(r.purpose, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(r.notes, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(v.vendor_name, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(v.friendly_name, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(c.category_name, '')) LIKE LOWER(?)
            )
            """
        )
        term = f"%{q}%"
        params.extend([term, term, term, term, term, term])

    if status:
        where.append("r.status = ?")
        params.append(status)

    where_sql = " AND ".join(f"({item})" for item in where)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                r.*,
                v.vendor_name,
                v.friendly_name AS vendor_friendly_name,
                c.category_name
            FROM finance_renewals r
            LEFT JOIN finance_vendors v
                ON v.id = r.primary_vendor_id
            LEFT JOIN finance_categories c
                ON c.id = r.category_id
            WHERE {where_sql}
            ORDER BY
                CASE r.status
                    WHEN 'active' THEN 1
                    WHEN 'under_review' THEN 2
                    WHEN 'planned' THEN 3
                    WHEN 'paused' THEN 4
                    WHEN 'discontinued' THEN 5
                    WHEN 'replaced' THEN 6
                    ELSE 7
                END,
                r.renewal_name COLLATE NOCASE
            """,
            params,
        ).fetchall()

    renewals = []

    for row in rows:
        renewal = dict(row)
        cycles = get_renewal_cycles(renewal["id"])
        renewal["cycles"] = cycles
        renewal["metrics"] = calculate_renewal_metrics(cycles)
        renewals.append(renewal)

    return renewals


def list_renewal_history(renewal_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                h.*,
                rc.fiscal_year_label
            FROM finance_renewal_history h
            LEFT JOIN finance_renewal_cycles rc
                ON rc.id = h.renewal_cycle_id
            WHERE h.renewal_id = ?
            ORDER BY h.changed_at DESC, h.id DESC
            """,
            (renewal_id,),
        ).fetchall()

    return [dict(row) for row in rows]

VALID_RELATIONSHIP_TYPES = {
    "primary_purchase",
    "campus_purchase",
    "additional_licenses",
    "adjustment",
    "credit",
    "implementation",
    "training",
    "supporting_purchase",
    "other",
}

VALID_LINK_SOURCES = {
    "manual",
    "confirmed_suggestion",
    "approved_rule",
    "automatic_match",
    "migration",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "annual",
    "for",
    "from",
    "inc",
    "invoice",
    "llc",
    "of",
    "payment",
    "purchase",
    "renewal",
    "service",
    "subscription",
    "the",
    "to",
}


def normalize_match_text(value: Any) -> str:
    value = normalize_text(value) or ""
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    words = [
        word
        for word in value.split()
        if word and word not in STOP_WORDS
    ]
    return " ".join(words)


def text_similarity(left: Any, right: Any) -> float:
    left_text = normalize_match_text(left)
    right_text = normalize_match_text(right)

    if not left_text or not right_text:
        return 0.0

    return SequenceMatcher(None, left_text, right_text).ratio()


def parse_date_year(value: Any) -> int | None:
    value = normalize_text(value)
    if not value:
        return None

    try:
        return datetime.fromisoformat(value).year
    except ValueError:
        return None


def normalize_relationship_type(value: Any) -> str:
    relationship_type = (
        normalize_text(value) or "primary_purchase"
    ).lower().replace(" ", "_")

    if relationship_type not in VALID_RELATIONSHIP_TYPES:
        raise ValueError(
            f"Invalid Renewal relationship type: {relationship_type}"
        )

    return relationship_type


def get_renewal_cycle_by_id(cycle_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                rc.*,
                r.renewal_name,
                r.department_name,
                r.primary_vendor_id,
                r.category_id,
                r.expected_renewal_hint,
                r.status AS renewal_status,
                v.vendor_name,
                v.friendly_name AS vendor_friendly_name
            FROM finance_renewal_cycles rc
            INNER JOIN finance_renewals r
                ON r.id = rc.renewal_id
            LEFT JOIN finance_vendors v
                ON v.id = r.primary_vendor_id
            WHERE rc.id = ?
            """,
            (cycle_id,),
        ).fetchone()

    return dict(row) if row else None


def get_record_renewal_link(record_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                l.*,
                rc.renewal_id,
                rc.fiscal_year_label,
                r.renewal_name
            FROM finance_renewal_record_links l
            INNER JOIN finance_renewal_cycles rc
                ON rc.id = l.renewal_cycle_id
            INNER JOIN finance_renewals r
                ON r.id = rc.renewal_id
            WHERE l.finance_record_id = ?
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()

    return dict(row) if row else None


def get_transaction_renewal_link(
    transaction_id: int,
) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                l.*,
                rc.renewal_id,
                rc.fiscal_year_label,
                r.renewal_name
            FROM finance_renewal_transaction_links l
            INNER JOIN finance_renewal_cycles rc
                ON rc.id = l.renewal_cycle_id
            INNER JOIN finance_renewals r
                ON r.id = rc.renewal_id
            WHERE l.finance_transaction_id = ?
            LIMIT 1
            """,
            (transaction_id,),
        ).fetchone()

    return dict(row) if row else None


def update_cycle_status_after_link(
    conn,
    renewal_cycle_id: int,
) -> None:
    current = conn.execute(
        """
        SELECT cycle_status
        FROM finance_renewal_cycles
        WHERE id = ?
        """,
        (renewal_cycle_id,),
    ).fetchone()

    if not current:
        return

    if current["cycle_status"] == "awaiting_activity":
        conn.execute(
            """
            UPDATE finance_renewal_cycles
            SET cycle_status = 'activity_found',
                updated_at = ?
            WHERE id = ?
            """,
            (utc_now_iso(), renewal_cycle_id),
        )


def update_cycle_status_after_unlink(
    conn,
    renewal_cycle_id: int,
) -> None:
    record_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM finance_renewal_record_links
        WHERE renewal_cycle_id = ?
        """,
        (renewal_cycle_id,),
    ).fetchone()["count"]

    transaction_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM finance_renewal_transaction_links
        WHERE renewal_cycle_id = ?
        """,
        (renewal_cycle_id,),
    ).fetchone()["count"]

    if record_count == 0 and transaction_count == 0:
        current = conn.execute(
            """
            SELECT cycle_status
            FROM finance_renewal_cycles
            WHERE id = ?
            """,
            (renewal_cycle_id,),
        ).fetchone()

        if current and current["cycle_status"] == "activity_found":
            conn.execute(
                """
                UPDATE finance_renewal_cycles
                SET cycle_status = 'awaiting_activity',
                    updated_at = ?
                WHERE id = ?
                """,
                (utc_now_iso(), renewal_cycle_id),
            )


def link_record_to_renewal_cycle(
    *,
    renewal_cycle_id: int,
    finance_record_id: int,
    relationship_type: str = "primary_purchase",
    counts_toward_cost: bool = True,
    link_source: str = "manual",
    confidence_score: float | None = None,
    linked_by_user_id: int | None = None,
) -> int:
    cycle = get_renewal_cycle_by_id(renewal_cycle_id)
    if not cycle:
        raise ValueError("Renewal cycle not found.")

    relationship_type = normalize_relationship_type(
        relationship_type
    )

    link_source = (
        normalize_text(link_source) or "manual"
    ).lower()

    if link_source not in VALID_LINK_SOURCES:
        raise ValueError("Invalid Renewal link source.")

    with get_connection() as conn:
        record = conn.execute(
            """
            SELECT *
            FROM finance_records
            WHERE id = ?
              AND status != 'deleted'
            """,
            (finance_record_id,),
        ).fetchone()

        if not record:
            raise ValueError("Finance record not found.")

        existing = conn.execute(
            """
            SELECT
                l.id,
                l.renewal_cycle_id,
                rc.renewal_id,
                rc.fiscal_year_label,
                r.renewal_name
            FROM finance_renewal_record_links l
            INNER JOIN finance_renewal_cycles rc
                ON rc.id = l.renewal_cycle_id
            INNER JOIN finance_renewals r
                ON r.id = rc.renewal_id
            WHERE l.finance_record_id = ?
            LIMIT 1
            """,
            (finance_record_id,),
        ).fetchone()

        if existing:
            if existing["renewal_cycle_id"] == renewal_cycle_id:
                raise ValueError(
                    "This Record is already linked to this Renewal cycle."
                )

            raise ValueError(
                "This Record is already linked to "
                f"{existing['renewal_name']} "
                f"({existing['fiscal_year_label']}). "
                "Unlink it before assigning it elsewhere."
            )

        now = utc_now_iso()

        cursor = conn.execute(
            """
            INSERT INTO finance_renewal_record_links (
                renewal_cycle_id,
                finance_record_id,
                relationship_type,
                counts_toward_cost,
                link_source,
                confidence_score,
                linked_by_user_id,
                linked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                renewal_cycle_id,
                finance_record_id,
                relationship_type,
                1 if counts_toward_cost else 0,
                link_source,
                confidence_score,
                linked_by_user_id,
                now,
            ),
        )

        update_cycle_status_after_link(
            conn,
            renewal_cycle_id,
        )

        conn.execute(
            """
            DELETE FROM finance_renewal_match_decisions
            WHERE renewal_id = ?
              AND candidate_type = 'record'
              AND candidate_id = ?
            """,
            (cycle["renewal_id"], finance_record_id),
        )

        conn.commit()

    add_renewal_history(
        renewal_id=cycle["renewal_id"],
        renewal_cycle_id=renewal_cycle_id,
        event_type="record_linked",
        summary=(
            f"Record {finance_record_id} linked as "
            f"{relationship_type.replace('_', ' ')}. "
            f"Counts toward cost: "
            f"{'Yes' if counts_toward_cost else 'No'}."
        ),
        source_type=link_source,
        confidence_score=confidence_score,
        changed_by_user_id=linked_by_user_id,
    )

    return cursor.lastrowid


def link_transaction_to_renewal_cycle(
    *,
    renewal_cycle_id: int,
    finance_transaction_id: int,
    relationship_type: str = "primary_purchase",
    counts_toward_cost: bool = True,
    link_source: str = "manual",
    confidence_score: float | None = None,
    linked_by_user_id: int | None = None,
) -> int:
    cycle = get_renewal_cycle_by_id(renewal_cycle_id)
    if not cycle:
        raise ValueError("Renewal cycle not found.")

    relationship_type = normalize_relationship_type(
        relationship_type
    )

    link_source = (
        normalize_text(link_source) or "manual"
    ).lower()

    if link_source not in VALID_LINK_SOURCES:
        raise ValueError("Invalid Renewal link source.")

    with get_connection() as conn:
        transaction = conn.execute(
            """
            SELECT *
            FROM finance_transactions
            WHERE id = ?
            """,
            (finance_transaction_id,),
        ).fetchone()

        if not transaction:
            raise ValueError("Ledger transaction not found.")

        existing = conn.execute(
            """
            SELECT
                l.id,
                l.renewal_cycle_id,
                rc.renewal_id,
                rc.fiscal_year_label,
                r.renewal_name
            FROM finance_renewal_transaction_links l
            INNER JOIN finance_renewal_cycles rc
                ON rc.id = l.renewal_cycle_id
            INNER JOIN finance_renewals r
                ON r.id = rc.renewal_id
            WHERE l.finance_transaction_id = ?
            LIMIT 1
            """,
            (finance_transaction_id,),
        ).fetchone()

        if existing:
            if existing["renewal_cycle_id"] == renewal_cycle_id:
                raise ValueError(
                    "This transaction is already linked to this "
                    "Renewal cycle."
                )

            raise ValueError(
                "This transaction is already linked to "
                f"{existing['renewal_name']} "
                f"({existing['fiscal_year_label']}). "
                "Unlink it before assigning it elsewhere."
            )

        now = utc_now_iso()

        cursor = conn.execute(
            """
            INSERT INTO finance_renewal_transaction_links (
                renewal_cycle_id,
                finance_transaction_id,
                relationship_type,
                counts_toward_cost,
                link_source,
                confidence_score,
                linked_by_user_id,
                linked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                renewal_cycle_id,
                finance_transaction_id,
                relationship_type,
                1 if counts_toward_cost else 0,
                link_source,
                confidence_score,
                linked_by_user_id,
                now,
            ),
        )

        update_cycle_status_after_link(
            conn,
            renewal_cycle_id,
        )

        conn.execute(
            """
            DELETE FROM finance_renewal_match_decisions
            WHERE renewal_id = ?
              AND candidate_type = 'transaction'
              AND candidate_id = ?
            """,
            (
                cycle["renewal_id"],
                finance_transaction_id,
            ),
        )

        conn.commit()

    add_renewal_history(
        renewal_id=cycle["renewal_id"],
        renewal_cycle_id=renewal_cycle_id,
        event_type="transaction_linked",
        summary=(
            f"Ledger transaction {finance_transaction_id} linked as "
            f"{relationship_type.replace('_', ' ')}. "
            f"Counts toward cost: "
            f"{'Yes' if counts_toward_cost else 'No'}."
        ),
        source_type=link_source,
        confidence_score=confidence_score,
        changed_by_user_id=linked_by_user_id,
    )

    return cursor.lastrowid


def unlink_record_from_renewal_cycle(
    *,
    renewal_cycle_id: int,
    finance_record_id: int,
    changed_by_user_id: int | None = None,
) -> bool:
    cycle = get_renewal_cycle_by_id(renewal_cycle_id)
    if not cycle:
        return False

    with get_connection() as conn:
        result = conn.execute(
            """
            DELETE FROM finance_renewal_record_links
            WHERE renewal_cycle_id = ?
              AND finance_record_id = ?
            """,
            (renewal_cycle_id, finance_record_id),
        )

        if result.rowcount == 0:
            return False

        update_cycle_status_after_unlink(
            conn,
            renewal_cycle_id,
        )
        conn.commit()

    add_renewal_history(
        renewal_id=cycle["renewal_id"],
        renewal_cycle_id=renewal_cycle_id,
        event_type="record_unlinked",
        summary=f"Record {finance_record_id} was unlinked.",
        changed_by_user_id=changed_by_user_id,
    )

    return True


def unlink_transaction_from_renewal_cycle(
    *,
    renewal_cycle_id: int,
    finance_transaction_id: int,
    changed_by_user_id: int | None = None,
) -> bool:
    cycle = get_renewal_cycle_by_id(renewal_cycle_id)
    if not cycle:
        return False

    with get_connection() as conn:
        result = conn.execute(
            """
            DELETE FROM finance_renewal_transaction_links
            WHERE renewal_cycle_id = ?
              AND finance_transaction_id = ?
            """,
            (renewal_cycle_id, finance_transaction_id),
        )

        if result.rowcount == 0:
            return False

        update_cycle_status_after_unlink(
            conn,
            renewal_cycle_id,
        )
        conn.commit()

    add_renewal_history(
        renewal_id=cycle["renewal_id"],
        renewal_cycle_id=renewal_cycle_id,
        event_type="transaction_unlinked",
        summary=(
            f"Ledger transaction {finance_transaction_id} "
            "was unlinked."
        ),
        changed_by_user_id=changed_by_user_id,
    )

    return True


def reject_renewal_candidate(
    *,
    renewal_id: int,
    renewal_cycle_id: int | None,
    candidate_type: str,
    candidate_id: int,
    reason: str | None = None,
    decided_by_user_id: int | None = None,
) -> None:
    candidate_type = (
        normalize_text(candidate_type) or ""
    ).lower()

    if candidate_type not in {"record", "transaction"}:
        raise ValueError("Invalid Renewal candidate type.")

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO finance_renewal_match_decisions (
                renewal_id,
                renewal_cycle_id,
                candidate_type,
                candidate_id,
                decision,
                decision_scope,
                reason,
                decided_by_user_id,
                decided_at
            )
            VALUES (?, ?, ?, ?, 'rejected', 'candidate', ?, ?, ?)
            ON CONFLICT(
                renewal_id,
                candidate_type,
                candidate_id
            )
            DO UPDATE SET
                renewal_cycle_id = excluded.renewal_cycle_id,
                decision = 'rejected',
                decision_scope = 'candidate',
                reason = excluded.reason,
                decided_by_user_id = excluded.decided_by_user_id,
                decided_at = excluded.decided_at
            """,
            (
                renewal_id,
                renewal_cycle_id,
                candidate_type,
                candidate_id,
                normalize_text(reason),
                decided_by_user_id,
                now,
            ),
        )
        conn.commit()

    add_renewal_history(
        renewal_id=renewal_id,
        renewal_cycle_id=renewal_cycle_id,
        event_type="match_rejected",
        summary=(
            f"{candidate_type.title()} {candidate_id} rejected "
            "as a Renewal match."
            + (
                f" Reason: {normalize_text(reason)}"
                if normalize_text(reason)
                else ""
            )
        ),
        source_type="manual",
        changed_by_user_id=decided_by_user_id,
    )


def get_linked_activity_for_cycle(
    renewal_cycle_id: int,
) -> dict:
    with get_connection() as conn:
        record_rows = conn.execute(
            """
            SELECT
                l.id AS link_id,
                l.relationship_type,
                l.counts_toward_cost,
                l.link_source,
                l.confidence_score,
                l.linked_at,
                r.id,
                r.title,
                r.department_name,
                r.po_number,
                r.purchase_date,
                r.cost,
                r.account_code,
                r.status,
                v.vendor_name,
                v.friendly_name AS vendor_friendly_name
            FROM finance_renewal_record_links l
            INNER JOIN finance_records r
                ON r.id = l.finance_record_id
            LEFT JOIN finance_vendors v
                ON v.id = r.vendor_id
            WHERE l.renewal_cycle_id = ?
            ORDER BY
                r.department_name COLLATE NOCASE,
                r.purchase_date,
                r.id
            """,
            (renewal_cycle_id,),
        ).fetchall()

        transaction_rows = conn.execute(
            """
            SELECT
                l.id AS link_id,
                l.relationship_type,
                l.counts_toward_cost,
                l.link_source,
                l.confidence_score,
                l.linked_at,
                t.id,
                t.department_name,
                t.purchase_date,
                t.vendor_name,
                t.po_number,
                t.account_code,
                t.description,
                t.expenditure_amount,
                t.encumbrance_amount,
                v.friendly_name AS vendor_friendly_name
            FROM finance_renewal_transaction_links l
            INNER JOIN finance_transactions t
                ON t.id = l.finance_transaction_id
            LEFT JOIN finance_vendors v
                ON v.id = t.vendor_id
            WHERE l.renewal_cycle_id = ?
            ORDER BY
                t.department_name COLLATE NOCASE,
                t.purchase_date,
                t.id
            """,
            (renewal_cycle_id,),
        ).fetchall()

    records = [dict(row) for row in record_rows]
    transactions = []

    for row in transaction_rows:
        item = dict(row)
        amount = (
            money_decimal(item.get("expenditure_amount"))
            + money_decimal(item.get("encumbrance_amount"))
        )
        item["amount"] = str(
            amount.quantize(Decimal("0.01"))
        )
        transactions.append(item)

    return {
        "records": records,
        "transactions": transactions,
    }


def calculate_department_breakdown(
    cycles: list[dict],
) -> list[dict]:
    totals: dict[str, Decimal] = {}

    for cycle in cycles:
        activity = get_linked_activity_for_cycle(cycle["id"])

        for record in activity["records"]:
            if not record["counts_toward_cost"]:
                continue

            department = (
                normalize_text(record.get("department_name"))
                or "Unassigned"
            )

            totals[department] = (
                totals.get(department, Decimal("0.00"))
                + money_decimal(record.get("cost"))
            )

        for transaction in activity["transactions"]:
            if not transaction["counts_toward_cost"]:
                continue

            department = (
                normalize_text(transaction.get("department_name"))
                or "Unassigned"
            )

            totals[department] = (
                totals.get(department, Decimal("0.00"))
                + money_decimal(transaction.get("amount"))
            )

    return [
        {
            "department_name": department,
            "total": str(amount.quantize(Decimal("0.01"))),
        }
        for department, amount in sorted(
            totals.items(),
            key=lambda item: (-item[1], item[0].lower()),
        )
    ]


def score_candidate(
    *,
    renewal: dict,
    cycle: dict,
    candidate: dict,
    candidate_type: str,
) -> dict:
    score = 0
    evidence = []

    renewal_vendor_id = renewal.get("primary_vendor_id")
    candidate_vendor_id = candidate.get("vendor_id")

    renewal_vendor_name = (
        renewal.get("vendor_friendly_name")
        or renewal.get("vendor_name")
    )

    candidate_vendor_name = (
        candidate.get("vendor_friendly_name")
        or candidate.get("vendor_name")
    )

    if (
        renewal_vendor_id
        and candidate_vendor_id
        and renewal_vendor_id == candidate_vendor_id
    ):
        score += 30
        evidence.append(
            {
                "points": 30,
                "label": "Same normalized vendor",
            }
        )
    elif (
        renewal_vendor_name
        and candidate_vendor_name
        and normalize_match_text(renewal_vendor_name)
        == normalize_match_text(candidate_vendor_name)
    ):
        score += 25
        evidence.append(
            {
                "points": 25,
                "label": "Vendor name matches",
            }
        )

    candidate_description = (
        candidate.get("title")
        if candidate_type == "record"
        else candidate.get("description")
    )

    description_similarity = text_similarity(
        renewal.get("renewal_name"),
        candidate_description,
    )

    if description_similarity >= 0.85:
        score += 30
        evidence.append(
            {
                "points": 30,
                "label": (
                    "Description strongly matches Renewal name "
                    f"({round(description_similarity * 100)}%)"
                ),
            }
        )
    elif description_similarity >= 0.65:
        score += 20
        evidence.append(
            {
                "points": 20,
                "label": (
                    "Description resembles Renewal name "
                    f"({round(description_similarity * 100)}%)"
                ),
            }
        )
    elif description_similarity >= 0.45:
        score += 10
        evidence.append(
            {
                "points": 10,
                "label": (
                    "Description partially resembles Renewal name "
                    f"({round(description_similarity * 100)}%)"
                ),
            }
        )

    candidate_date = candidate.get("purchase_date")
    candidate_year = parse_date_year(candidate_date)

    cycle_year = None

    if cycle.get("fiscal_year_id"):
        with get_connection() as conn:
            year_row = conn.execute(
                """
                SELECT start_date, end_date
                FROM finance_fiscal_years
                WHERE id = ?
                """,
                (cycle["fiscal_year_id"],),
            ).fetchone()

        if year_row and candidate_date:
            if (
                year_row["start_date"]
                <= candidate_date
                <= year_row["end_date"]
            ):
                score += 15
                evidence.append(
                    {
                        "points": 15,
                        "label": "Purchase falls within this fiscal year",
                    }
                )
    elif candidate_year:
        normalized_label = normalize_match_text(
            cycle.get("fiscal_year_label")
        )

        if str(candidate_year) in normalized_label:
            score += 10
            evidence.append(
                {
                    "points": 10,
                    "label": "Purchase year matches cycle label",
                }
            )

    expected_cost = money_decimal(cycle.get("expected_cost"))

    if candidate_type == "record":
        candidate_cost = money_decimal(candidate.get("cost"))
    else:
        candidate_cost = (
            money_decimal(candidate.get("expenditure_amount"))
            + money_decimal(candidate.get("encumbrance_amount"))
        )

    if expected_cost > Decimal("0.00") and candidate_cost > Decimal("0.00"):
        difference_ratio = abs(
            candidate_cost - expected_cost
        ) / expected_cost

        if difference_ratio <= Decimal("0.10"):
            score += 15
            evidence.append(
                {
                    "points": 15,
                    "label": "Amount is within 10% of expected cost",
                }
            )
        elif difference_ratio <= Decimal("0.25"):
            score += 8
            evidence.append(
                {
                    "points": 8,
                    "label": "Amount is within 25% of expected cost",
                }
            )

    if renewal.get("expected_renewal_hint"):
        score += 5
        evidence.append(
            {
                "points": 5,
                "label": "Renewal was manually marked as expected",
            }
        )

    score = min(score, 100)

    if score >= 85:
        confidence_label = "High confidence"
    elif score >= 65:
        confidence_label = "Suggested match"
    elif score >= 45:
        confidence_label = "Possible match"
    else:
        confidence_label = "Low confidence"

    return {
        "score": score,
        "confidence_label": confidence_label,
        "evidence": evidence,
    }


def find_renewal_candidates(
    *,
    renewal_id: int,
    renewal_cycle_id: int,
    minimum_score: int = 35,
    limit: int = 100,
) -> dict:
    renewal = get_renewal_by_id(renewal_id)
    cycle = get_renewal_cycle_by_id(renewal_cycle_id)

    if not renewal or not cycle:
        return {
            "records": [],
            "transactions": [],
        }

    vendor_id = renewal.get("primary_vendor_id")
    vendor_name = (
        renewal.get("vendor_friendly_name")
        or renewal.get("vendor_name")
    )

    with get_connection() as conn:
        record_rows = conn.execute(
            """
            SELECT
                r.*,
                v.vendor_name,
                v.friendly_name AS vendor_friendly_name
            FROM finance_records r
            LEFT JOIN finance_vendors v
                ON v.id = r.vendor_id
            LEFT JOIN finance_renewal_record_links linked
                ON linked.finance_record_id = r.id
            LEFT JOIN finance_renewal_match_decisions rejected
                ON rejected.renewal_id = ?
               AND rejected.candidate_type = 'record'
               AND rejected.candidate_id = r.id
               AND rejected.decision = 'rejected'
            WHERE r.status NOT IN ('archived', 'deleted')
              AND linked.id IS NULL
              AND rejected.id IS NULL
              AND (
                    r.vendor_id = ?
                    OR LOWER(COALESCE(v.vendor_name, ''))
                       LIKE LOWER(?)
                    OR LOWER(COALESCE(r.title, ''))
                       LIKE LOWER(?)
              )
            ORDER BY r.purchase_date DESC, r.id DESC
            LIMIT ?
            """,
            (
                renewal_id,
                vendor_id,
                f"%{vendor_name or ''}%",
                f"%{renewal['renewal_name']}%",
                limit,
            ),
        ).fetchall()

        transaction_rows = conn.execute(
            """
            SELECT
                t.*,
                v.friendly_name AS vendor_friendly_name
            FROM finance_transactions t
            LEFT JOIN finance_vendors v
                ON v.id = t.vendor_id
            LEFT JOIN finance_renewal_transaction_links linked
                ON linked.finance_transaction_id = t.id
            LEFT JOIN finance_renewal_match_decisions rejected
                ON rejected.renewal_id = ?
               AND rejected.candidate_type = 'transaction'
               AND rejected.candidate_id = t.id
               AND rejected.decision = 'rejected'
            WHERE linked.id IS NULL
              AND rejected.id IS NULL
              AND (
                    t.vendor_id = ?
                    OR LOWER(COALESCE(t.vendor_name, ''))
                       LIKE LOWER(?)
                    OR LOWER(COALESCE(t.description, ''))
                       LIKE LOWER(?)
              )
            ORDER BY t.purchase_date DESC, t.id DESC
            LIMIT ?
            """,
            (
                renewal_id,
                vendor_id,
                f"%{vendor_name or ''}%",
                f"%{renewal['renewal_name']}%",
                limit,
            ),
        ).fetchall()

    records = []

    for row in record_rows:
        candidate = dict(row)
        match = score_candidate(
            renewal=renewal,
            cycle=cycle,
            candidate=candidate,
            candidate_type="record",
        )

        if match["score"] < minimum_score:
            continue

        candidate["match"] = match
        records.append(candidate)

    transactions = []

    for row in transaction_rows:
        candidate = dict(row)
        amount = (
            money_decimal(candidate.get("expenditure_amount"))
            + money_decimal(candidate.get("encumbrance_amount"))
        )
        candidate["amount"] = str(
            amount.quantize(Decimal("0.01"))
        )

        match = score_candidate(
            renewal=renewal,
            cycle=cycle,
            candidate=candidate,
            candidate_type="transaction",
        )

        if match["score"] < minimum_score:
            continue

        candidate["match"] = match
        transactions.append(candidate)

    records.sort(
        key=lambda item: (
            -item["match"]["score"],
            item.get("purchase_date") or "",
        )
    )

    transactions.sort(
        key=lambda item: (
            -item["match"]["score"],
            item.get("purchase_date") or "",
        )
    )

    return {
        "records": records,
        "transactions": transactions,
    }

def parse_iso_date_value(value: Any) -> date | None:
    value = normalize_text(value)
    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def build_inferred_fiscal_year_label(
    fiscal_year_end_year: int,
) -> str:
    return f"FY{str(fiscal_year_end_year)[-2:]}"


def safe_date(
    year: int,
    month: int,
    day: int,
) -> date:
    safe_day = min(day, monthrange(year, month)[1])
    return date(year, month, safe_day)


def infer_fiscal_year_from_date(
    purchase_date: str | None,
) -> dict | None:
    """
    Determine the fiscal year for a date.

    Preference order:
    1. An explicitly configured fiscal year containing the date.
    2. Infer the year using the start/end pattern of an existing
       configured fiscal year.

    This does not create a finance_fiscal_years row.
    """
    activity_date = parse_iso_date_value(purchase_date)
    if not activity_date:
        return None

    with get_connection() as conn:
        configured = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_years
            WHERE DATE(?) BETWEEN DATE(start_date) AND DATE(end_date)
            ORDER BY is_current DESC, is_next DESC, year_number DESC
            LIMIT 1
            """,
            (activity_date.isoformat(),),
        ).fetchone()

        if configured:
            configured = dict(configured)

            return {
                "fiscal_year_id": configured["id"],
                "fiscal_year_label": get_fiscal_year_label(
                    configured
                ),
                "start_date": configured["start_date"],
                "end_date": configured["end_date"],
                "is_inferred": False,
            }

        template = conn.execute(
            """
            SELECT *
            FROM finance_fiscal_years
            ORDER BY
                is_current DESC,
                is_next DESC,
                year_number DESC,
                start_date DESC
            LIMIT 1
            """
        ).fetchone()

    if not template:
        return None

    template = dict(template)

    template_start = parse_iso_date_value(
        template.get("start_date")
    )
    template_end = parse_iso_date_value(
        template.get("end_date")
    )

    if not template_start or not template_end:
        return None

    start_month = template_start.month
    start_day = template_start.day
    end_month = template_end.month
    end_day = template_end.day

    crosses_calendar_year = (
        (end_month, end_day) < (start_month, start_day)
    )

    candidate_start = safe_date(
        activity_date.year,
        start_month,
        start_day,
    )

    if crosses_calendar_year:
        if activity_date >= candidate_start:
            start_year = activity_date.year
            end_year = activity_date.year + 1
        else:
            start_year = activity_date.year - 1
            end_year = activity_date.year
    else:
        if activity_date >= candidate_start:
            start_year = activity_date.year
            end_year = activity_date.year
        else:
            start_year = activity_date.year - 1
            end_year = activity_date.year - 1

    inferred_start = safe_date(
        start_year,
        start_month,
        start_day,
    )
    inferred_end = safe_date(
        end_year,
        end_month,
        end_day,
    )

    return {
        "fiscal_year_id": None,
        "fiscal_year_label": build_inferred_fiscal_year_label(
            end_year
        ),
        "start_date": inferred_start.isoformat(),
        "end_date": inferred_end.isoformat(),
        "is_inferred": True,
    }


def find_or_create_cycle_for_activity_date(
    *,
    renewal_id: int,
    selected_cycle_id: int,
    purchase_date: str | None,
    changed_by_user_id: int | None = None,
) -> dict:
    """
    Return the cycle that actually corresponds to the activity date.

    If that fiscal year has not been configured, create an inferred
    Renewal cycle such as FY26 with fiscal_year_id = NULL.
    """
    selected_cycle = get_renewal_cycle_by_id(
        selected_cycle_id
    )

    if not selected_cycle:
        raise ValueError("Selected Renewal cycle not found.")

    inferred_year = infer_fiscal_year_from_date(
        purchase_date
    )

    if not inferred_year:
        return selected_cycle

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM finance_renewal_cycles
            WHERE renewal_id = ?
              AND (
                    fiscal_year_id = ?
                    OR LOWER(TRIM(fiscal_year_label))
                       = LOWER(TRIM(?))
              )
            ORDER BY
                CASE
                    WHEN fiscal_year_id IS NOT NULL THEN 0
                    ELSE 1
                END,
                id
            LIMIT 1
            """,
            (
                renewal_id,
                inferred_year["fiscal_year_id"],
                inferred_year["fiscal_year_label"],
            ),
        ).fetchone()

    if existing:
        return dict(existing)

    cycle_id = create_renewal_cycle(
        renewal_id=renewal_id,
        fiscal_year_id=inferred_year["fiscal_year_id"],
        fiscal_year_label=inferred_year[
            "fiscal_year_label"
        ],
        cycle_status="awaiting_activity",
        service_start_date=inferred_year["start_date"],
        service_end_date=inferred_year["end_date"],
        created_by_user_id=changed_by_user_id,
    )

    cycle = get_renewal_cycle_by_id(cycle_id)

    add_renewal_history(
        renewal_id=renewal_id,
        renewal_cycle_id=cycle_id,
        event_type="fiscal_year_inferred",
        summary=(
            f"{inferred_year['fiscal_year_label']} was inferred "
            f"from purchase date {purchase_date} using the "
            "configured fiscal-year date pattern."
        ),
        source_type="system",
        changed_by_user_id=changed_by_user_id,
    )

    return cycle

def get_record_for_renewal_link(
    record_id: int,
) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM finance_records
            WHERE id = ?
              AND status != 'deleted'
            """,
            (record_id,),
        ).fetchone()

    return dict(row) if row else None

def get_transaction_for_renewal_link(
    transaction_id: int,
) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM finance_transactions
            WHERE id = ?
            """,
            (transaction_id,),
        ).fetchone()

    return dict(row) if row else None

def describe_field_change(
    label: str,
    old_value: Any,
    new_value: Any,
) -> str | None:
    old_text = normalize_text(old_value) or "—"
    new_text = normalize_text(new_value) or "—"

    if old_text == new_text:
        return None

    return f"{label}: {old_text} → {new_text}"


def update_renewal(
    *,
    renewal_id: int,
    renewal_name: str,
    primary_vendor_id: int | None,
    category_id: int | None,
    purpose: str | None,
    status: str,
    expected_renewal_hint: bool,
    default_notification_days: int,
    notification_recipients: str | None,
    notes: str | None,
    changed_by_user_id: int | None = None,
) -> None:
    existing = get_renewal_by_id(renewal_id)
    if not existing:
        raise ValueError("Renewal not found.")

    renewal_name = normalize_text(renewal_name)
    if not renewal_name:
        raise ValueError("Renewal name is required.")

    status = normalize_status(
        status,
        VALID_RENEWAL_STATUSES,
        "active",
    )

    try:
        default_notification_days = int(
            default_notification_days or 30
        )
    except (TypeError, ValueError):
        default_notification_days = 30

    default_notification_days = max(
        default_notification_days,
        0,
    )

    with get_connection() as conn:
        duplicate = conn.execute(
            """
            SELECT id
            FROM finance_renewals
            WHERE department_name = ?
              AND LOWER(TRIM(renewal_name)) = LOWER(TRIM(?))
              AND id != ?
              AND status NOT IN ('discontinued', 'replaced')
            LIMIT 1
            """,
            (
                existing["department_name"],
                renewal_name,
                renewal_id,
            ),
        ).fetchone()

        if duplicate:
            raise ValueError(
                "Another active Renewal with this name already "
                "exists for the department."
            )

        conn.execute(
            """
            UPDATE finance_renewals
            SET
                renewal_name = ?,
                primary_vendor_id = ?,
                category_id = ?,
                purpose = ?,
                status = ?,
                expected_renewal_hint = ?,
                default_notification_days = ?,
                notification_recipients = ?,
                notes = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                renewal_name,
                primary_vendor_id,
                category_id,
                normalize_text(purpose),
                status,
                1 if expected_renewal_hint else 0,
                default_notification_days,
                normalize_text(notification_recipients),
                normalize_text(notes),
                utc_now_iso(),
                renewal_id,
            ),
        )
        conn.commit()

    changes = [
        describe_field_change(
            "Name",
            existing.get("renewal_name"),
            renewal_name,
        ),
        describe_field_change(
            "Vendor",
            existing.get("primary_vendor_id"),
            primary_vendor_id,
        ),
        describe_field_change(
            "Category",
            existing.get("category_id"),
            category_id,
        ),
        describe_field_change(
            "Purpose",
            existing.get("purpose"),
            purpose,
        ),
        describe_field_change(
            "Status",
            existing.get("status"),
            status,
        ),
        describe_field_change(
            "Expected renewal hint",
            existing.get("expected_renewal_hint"),
            1 if expected_renewal_hint else 0,
        ),
        describe_field_change(
            "Notification days",
            existing.get("default_notification_days"),
            default_notification_days,
        ),
        describe_field_change(
            "Notification recipients",
            existing.get("notification_recipients"),
            notification_recipients,
        ),
        describe_field_change(
            "Notes",
            existing.get("notes"),
            notes,
        ),
    ]

    summary = "; ".join(
        change for change in changes if change
    ) or "Renewal saved without field changes."

    add_renewal_history(
        renewal_id=renewal_id,
        event_type="renewal_updated",
        summary=summary,
        changed_by_user_id=changed_by_user_id,
    )


def update_renewal_cycle(
    *,
    cycle_id: int,
    fiscal_year_id: int | None,
    fiscal_year_label: str | None,
    cycle_status: str,
    renewal_date: str | None,
    service_start_date: str | None,
    service_end_date: str | None,
    expected_cost: str | None,
    decision: str | None,
    decision_notes: str | None,
    changed_by_user_id: int | None = None,
) -> None:
    existing = get_renewal_cycle_by_id(cycle_id)
    if not existing:
        raise ValueError("Renewal cycle not found.")

    cycle_status = normalize_status(
        cycle_status,
        VALID_CYCLE_STATUSES,
        "awaiting_activity",
    )

    fiscal_year = get_fiscal_year_by_id(fiscal_year_id)

    if fiscal_year:
        fiscal_year_label = get_fiscal_year_label(
            fiscal_year
        )
    else:
        fiscal_year_label = normalize_text(
            fiscal_year_label
        )

    if not fiscal_year_label:
        raise ValueError("Fiscal year label is required.")

    expected_cost = normalize_money(expected_cost)
    decision = normalize_text(decision)
    now = utc_now_iso()

    with get_connection() as conn:
        duplicate = conn.execute(
            """
            SELECT id
            FROM finance_renewal_cycles
            WHERE renewal_id = ?
              AND LOWER(TRIM(fiscal_year_label))
                  = LOWER(TRIM(?))
              AND id != ?
            LIMIT 1
            """,
            (
                existing["renewal_id"],
                fiscal_year_label,
                cycle_id,
            ),
        ).fetchone()

        if duplicate:
            raise ValueError(
                f"A {fiscal_year_label} cycle already exists."
            )

        finalized_at = existing.get("finalized_at")

        if decision in {
            "renewed",
            "not_renewed",
            "cancelled",
        } and not finalized_at:
            finalized_at = now

        if not decision:
            finalized_at = None

        conn.execute(
            """
            UPDATE finance_renewal_cycles
            SET
                fiscal_year_id = ?,
                fiscal_year_label = ?,
                cycle_status = ?,
                renewal_date = ?,
                service_start_date = ?,
                service_end_date = ?,
                expected_cost = ?,
                decision = ?,
                decision_notes = ?,
                finalized_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                fiscal_year_id,
                fiscal_year_label,
                cycle_status,
                normalize_text(renewal_date),
                normalize_text(service_start_date),
                normalize_text(service_end_date),
                expected_cost,
                decision,
                normalize_text(decision_notes),
                finalized_at,
                now,
                cycle_id,
            ),
        )
        conn.commit()

    changes = [
        describe_field_change(
            "Fiscal year",
            existing.get("fiscal_year_label"),
            fiscal_year_label,
        ),
        describe_field_change(
            "Status",
            existing.get("cycle_status"),
            cycle_status,
        ),
        describe_field_change(
            "Renewal date",
            existing.get("renewal_date"),
            renewal_date,
        ),
        describe_field_change(
            "Service start",
            existing.get("service_start_date"),
            service_start_date,
        ),
        describe_field_change(
            "Service end",
            existing.get("service_end_date"),
            service_end_date,
        ),
        describe_field_change(
            "Expected cost",
            existing.get("expected_cost"),
            expected_cost,
        ),
        describe_field_change(
            "Decision",
            existing.get("decision"),
            decision,
        ),
        describe_field_change(
            "Decision notes",
            existing.get("decision_notes"),
            decision_notes,
        ),
    ]

    summary = "; ".join(
        change for change in changes if change
    ) or "Annual cycle saved without field changes."

    add_renewal_history(
        renewal_id=existing["renewal_id"],
        renewal_cycle_id=cycle_id,
        event_type="cycle_updated",
        summary=summary,
        changed_by_user_id=changed_by_user_id,
    )


def get_cycle_link_counts(cycle_id: int) -> dict:
    with get_connection() as conn:
        record_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM finance_renewal_record_links
            WHERE renewal_cycle_id = ?
            """,
            (cycle_id,),
        ).fetchone()["count"]

        transaction_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM finance_renewal_transaction_links
            WHERE renewal_cycle_id = ?
            """,
            (cycle_id,),
        ).fetchone()["count"]

    return {
        "records": int(record_count or 0),
        "transactions": int(transaction_count or 0),
        "total": int(record_count or 0)
        + int(transaction_count or 0),
    }


def delete_empty_renewal_cycle(
    *,
    cycle_id: int,
    changed_by_user_id: int | None = None,
) -> bool:
    cycle = get_renewal_cycle_by_id(cycle_id)
    if not cycle:
        return False

    counts = get_cycle_link_counts(cycle_id)

    if counts["total"] > 0:
        raise ValueError(
            "This annual cycle contains linked financial activity. "
            "Unlink or move the activity before deleting the cycle."
        )

    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM finance_renewal_match_decisions
            WHERE renewal_cycle_id = ?
            """,
            (cycle_id,),
        )

        conn.execute(
            """
            DELETE FROM finance_renewal_cycles
            WHERE id = ?
            """,
            (cycle_id,),
        )

        conn.commit()

    add_renewal_history(
        renewal_id=cycle["renewal_id"],
        event_type="cycle_deleted",
        summary=(
            f"Empty annual cycle "
            f"{cycle['fiscal_year_label']} deleted."
        ),
        changed_by_user_id=changed_by_user_id,
    )

    return True


def update_record_renewal_link(
    *,
    finance_record_id: int,
    current_cycle_id: int,
    target_cycle_id: int,
    relationship_type: str,
    counts_toward_cost: bool,
    changed_by_user_id: int | None = None,
) -> None:
    relationship_type = normalize_relationship_type(
        relationship_type
    )

    current_cycle = get_renewal_cycle_by_id(
        current_cycle_id
    )
    target_cycle = get_renewal_cycle_by_id(
        target_cycle_id
    )

    if not current_cycle or not target_cycle:
        raise ValueError("Renewal cycle not found.")

    if (
        current_cycle["renewal_id"]
        != target_cycle["renewal_id"]
    ):
        raise ValueError(
            "Activity can only be moved between cycles of the "
            "same Renewal."
        )

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM finance_renewal_record_links
            WHERE finance_record_id = ?
              AND renewal_cycle_id = ?
            """,
            (
                finance_record_id,
                current_cycle_id,
            ),
        ).fetchone()

        if not existing:
            raise ValueError("Record link not found.")

        duplicate = conn.execute(
            """
            SELECT id
            FROM finance_renewal_record_links
            WHERE finance_record_id = ?
              AND renewal_cycle_id = ?
              AND id != ?
            LIMIT 1
            """,
            (
                finance_record_id,
                target_cycle_id,
                existing["id"],
            ),
        ).fetchone()

        if duplicate:
            raise ValueError(
                "This Record is already linked to the target cycle."
            )

        conn.execute(
            """
            UPDATE finance_renewal_record_links
            SET
                renewal_cycle_id = ?,
                relationship_type = ?,
                counts_toward_cost = ?
            WHERE id = ?
            """,
            (
                target_cycle_id,
                relationship_type,
                1 if counts_toward_cost else 0,
                existing["id"],
            ),
        )

        update_cycle_status_after_link(
            conn,
            target_cycle_id,
        )

        if target_cycle_id != current_cycle_id:
            update_cycle_status_after_unlink(
                conn,
                current_cycle_id,
            )

        conn.commit()

    add_renewal_history(
        renewal_id=current_cycle["renewal_id"],
        renewal_cycle_id=target_cycle_id,
        event_type=(
            "record_moved"
            if target_cycle_id != current_cycle_id
            else "record_link_updated"
        ),
        summary=(
            f"Record {finance_record_id}: "
            f"{current_cycle['fiscal_year_label']} → "
            f"{target_cycle['fiscal_year_label']}; "
            f"relationship "
            f"{relationship_type.replace('_', ' ')}; "
            f"counts toward cost "
            f"{'Yes' if counts_toward_cost else 'No'}."
        ),
        changed_by_user_id=changed_by_user_id,
    )


def update_transaction_renewal_link(
    *,
    finance_transaction_id: int,
    current_cycle_id: int,
    target_cycle_id: int,
    relationship_type: str,
    counts_toward_cost: bool,
    changed_by_user_id: int | None = None,
) -> None:
    relationship_type = normalize_relationship_type(
        relationship_type
    )

    current_cycle = get_renewal_cycle_by_id(
        current_cycle_id
    )
    target_cycle = get_renewal_cycle_by_id(
        target_cycle_id
    )

    if not current_cycle or not target_cycle:
        raise ValueError("Renewal cycle not found.")

    if (
        current_cycle["renewal_id"]
        != target_cycle["renewal_id"]
    ):
        raise ValueError(
            "Activity can only be moved between cycles of the "
            "same Renewal."
        )

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM finance_renewal_transaction_links
            WHERE finance_transaction_id = ?
              AND renewal_cycle_id = ?
            """,
            (
                finance_transaction_id,
                current_cycle_id,
            ),
        ).fetchone()

        if not existing:
            raise ValueError("Transaction link not found.")

        duplicate = conn.execute(
            """
            SELECT id
            FROM finance_renewal_transaction_links
            WHERE finance_transaction_id = ?
              AND renewal_cycle_id = ?
              AND id != ?
            LIMIT 1
            """,
            (
                finance_transaction_id,
                target_cycle_id,
                existing["id"],
            ),
        ).fetchone()

        if duplicate:
            raise ValueError(
                "This transaction is already linked to the "
                "target cycle."
            )

        conn.execute(
            """
            UPDATE finance_renewal_transaction_links
            SET
                renewal_cycle_id = ?,
                relationship_type = ?,
                counts_toward_cost = ?
            WHERE id = ?
            """,
            (
                target_cycle_id,
                relationship_type,
                1 if counts_toward_cost else 0,
                existing["id"],
            ),
        )

        update_cycle_status_after_link(
            conn,
            target_cycle_id,
        )

        if target_cycle_id != current_cycle_id:
            update_cycle_status_after_unlink(
                conn,
                current_cycle_id,
            )

        conn.commit()

    add_renewal_history(
        renewal_id=current_cycle["renewal_id"],
        renewal_cycle_id=target_cycle_id,
        event_type=(
            "transaction_moved"
            if target_cycle_id != current_cycle_id
            else "transaction_link_updated"
        ),
        summary=(
            f"Transaction {finance_transaction_id}: "
            f"{current_cycle['fiscal_year_label']} → "
            f"{target_cycle['fiscal_year_label']}; "
            f"relationship "
            f"{relationship_type.replace('_', ' ')}; "
            f"counts toward cost "
            f"{'Yes' if counts_toward_cost else 'No'}."
        ),
        changed_by_user_id=changed_by_user_id,
    )