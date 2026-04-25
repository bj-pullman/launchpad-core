from datetime import datetime, timezone

from apps.finance.db import get_connection


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


EFINANCE_DAILY_PROFILE_NAME = "eFinance Daily Expenditure Report"


def ensure_efinance_daily_import_profile(created_by_user_id=None):
    now = utc_now_iso()

    mappings = [
        ("FUND", "fund", None, None, 0),
        ("BUDGET UNIT", "budget_unit", None, None, 0),
        ("ACCOUNT", "account_code", None, None, 0),
        ("DATE", "purchase_date", "date", None, 0),
        ("PURCHASE O", "po_number", None, None, 0),
        ("VENDOR", "vendor_name", "vendor_split", None, 0),
        ("EXPENDITURES", "expenditure_amount", "money", None, 0),
        ("ENCUMBRANCES", "encumbrance_amount", "money", None, 0),
        ("DESCRIPTION", "description", None, None, 0),
        ("CUMULATIVE BALANCE", "cumulative_balance", "money", None, 0),
    ]

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM finance_import_profiles
            WHERE profile_name = ?
            """,
            (EFINANCE_DAILY_PROFILE_NAME,),
        ).fetchone()

        if row:
            return row["id"]
        else:
            cursor = conn.execute(
                """
                INSERT INTO finance_import_profiles (
                    profile_name,
                    source_type,
                    target_area,
                    is_active,
                    description,
                    created_by_user_id,
                    created_at,
                    updated_at
                )
                VALUES (?, 'efinance', 'transactions', 1, ?, ?, ?, ?)
                """,
                (
                    EFINANCE_DAILY_PROFILE_NAME,
                    "Default profile for daily eFinance expenditure report imports.",
                    created_by_user_id,
                    now,
                    now,
                ),
            )
            profile_id = cursor.lastrowid

        # Reset mappings (safe/idempotent)
        conn.execute(
            "DELETE FROM finance_import_profile_fields WHERE profile_id = ?",
            (profile_id,),
        )

        for source_column, target_field, transform_rule, default_value, required in mappings:
            conn.execute(
                """
                INSERT INTO finance_import_profile_fields (
                    profile_id,
                    source_column_name,
                    target_field_name,
                    transform_rule,
                    default_value,
                    required,
                    ignore_field,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    profile_id,
                    source_column,
                    target_field,
                    transform_rule,
                    default_value,
                    required,
                    now,
                    now,
                ),
            )

        conn.commit()

    return profile_id