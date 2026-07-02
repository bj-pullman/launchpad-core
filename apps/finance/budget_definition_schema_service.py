from __future__ import annotations

from .db import get_connection


def _ensure_column(conn, table_name: str, column_name: str, column_sql: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def ensure_budget_definition_schema() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS finance_budget_definition_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiscal_year TEXT NOT NULL,
                source_filename TEXT NULL,
                uploaded_by_user_id INTEGER NULL,
                uploaded_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                notes TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_budget_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                definition_set_id INTEGER NULL,
                fiscal_year TEXT NOT NULL,
                level_number INTEGER NULL,
                code TEXT NULL,
                fund_code TEXT NULL,
                function_code TEXT NULL,
                building_code TEXT NULL,
                program_code TEXT NULL,
                modifier_code TEXT NULL,
                combined_code TEXT NULL,
                title TEXT NULL,
                description TEXT NULL,
                raw_json TEXT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        for column_name, column_sql in {
            "definition_set_id": "INTEGER NULL",
            "level_number": "INTEGER NULL",
            "code": "TEXT NULL",
            "title": "TEXT NULL",
            "raw_json": "TEXT NULL",
            "function_code": "TEXT NULL",
            "building_code": "TEXT NULL",
            "program_code": "TEXT NULL",
            "modifier_code": "TEXT NULL",
        }.items():
            _ensure_column(conn, "finance_budget_definitions", column_name, column_sql)

        for column_name, column_sql in {
            "budget_definition_id": "INTEGER NULL",
            "budget_definition_status": "TEXT NULL",
        }.items():
            _ensure_column(conn, "finance_transactions", column_name, column_sql)

        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_finance_budget_definition_sets_active
            ON finance_budget_definition_sets(fiscal_year, is_active, uploaded_at);

            CREATE INDEX IF NOT EXISTS idx_finance_budget_definitions_set
            ON finance_budget_definitions(definition_set_id);

            CREATE INDEX IF NOT EXISTS idx_finance_budget_definitions_combined
            ON finance_budget_definitions(fiscal_year, combined_code);
            """
        )
        conn.commit()
