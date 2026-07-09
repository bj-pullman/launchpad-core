from pathlib import Path
import sqlite3
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parents[2]
FINANCE_DIR = BASE_DIR / "instance" / "finance"
DATA_DIR = FINANCE_DIR / "data"
DB_PATH = DATA_DIR / "finance.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn, table_name: str, column_name: str, column_sql: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def init_finance_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS finance_departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_name TEXT NOT NULL UNIQUE,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_user_department_scope (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                department_name TEXT NOT NULL,
                area_key TEXT NOT NULL DEFAULT 'finance',
                scope_level TEXT NOT NULL DEFAULT 'operator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, department_name, area_key)
            );

            CREATE TABLE IF NOT EXISTS finance_vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_name TEXT NOT NULL UNIQUE,
                friendly_name TEXT NULL,
                vendor_code TEXT NULL,
                website TEXT NULL,
                main_phone TEXT NULL,
                billing_email TEXT NULL,
                support_email TEXT NULL,
                sales_contact_name TEXT NULL,
                sales_contact_email TEXT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                notes TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                deleted_at TEXT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT NOT NULL UNIQUE,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_category_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                alias_name TEXT NOT NULL,
                normalized_alias TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_category_import_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                imported_category_name TEXT NOT NULL,
                normalized_imported_name TEXT NOT NULL UNIQUE,
                suggested_category_id INTEGER NULL,
                confidence_score REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_finance_category_aliases_category
            ON finance_category_aliases(category_id);

            CREATE INDEX IF NOT EXISTS idx_finance_category_suggestions_status
            ON finance_category_import_suggestions(status, confidence_score);

            CREATE TABLE IF NOT EXISTS finance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type TEXT NOT NULL DEFAULT 'renewal',
                title TEXT NOT NULL,
                vendor_id INTEGER NULL,
                category_id INTEGER NULL,
                department_name TEXT NOT NULL,
                account_code TEXT NULL,
                po_number TEXT NULL,
                purchase_date TEXT NULL,
                service_start_date TEXT NULL,
                use_purchase_date_as_start INTEGER NOT NULL DEFAULT 1,
                term_length INTEGER NULL,
                term_unit TEXT NULL,
                expiration_date TEXT NULL,
                renewal_date TEXT NULL,
                notify_days_before INTEGER NOT NULL DEFAULT 30,
                notification_recipients TEXT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                cost TEXT NULL,
                notes TEXT NULL,
                created_by_user_id INTEGER NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_record_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                finance_record_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT NULL,
                changed_by_user_id INTEGER NULL,
                changed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_import_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_name TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                target_area TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                description TEXT NULL,
                created_by_user_id INTEGER NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_import_profile_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                source_column_name TEXT NULL,
                target_field_name TEXT NOT NULL,
                transform_rule TEXT NULL,
                default_value TEXT NULL,
                required INTEGER NOT NULL DEFAULT 0,
                ignore_field INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_type TEXT NOT NULL,
                source_type TEXT NOT NULL,
                profile_id INTEGER NULL,
                original_filename TEXT NULL,
                stored_filename TEXT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                total_rows INTEGER NOT NULL DEFAULT 0,
                created_rows INTEGER NOT NULL DEFAULT 0,
                updated_rows INTEGER NOT NULL DEFAULT 0,
                skipped_rows INTEGER NOT NULL DEFAULT 0,
                error_rows INTEGER NOT NULL DEFAULT 0,
                run_notes TEXT NULL,
                started_by_user_id INTEGER NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_import_run_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                row_number INTEGER NULL,
                source_identifier TEXT NULL,
                error_message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_import_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                host TEXT NULL,
                port INTEGER NULL,
                username TEXT NULL,
                password_secret_ref TEXT NULL,
                remote_path TEXT NULL,
                archive_path TEXT NULL,
                profile_id INTEGER NULL,
                target_area TEXT NOT NULL DEFAULT 'records',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                finance_record_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                stored_name TEXT NOT NULL UNIQUE,
                mime_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                document_type TEXT NOT NULL DEFAULT 'other',
                uploaded_by_user_id INTEGER NULL,
                uploaded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_name TEXT NOT NULL,
                import_run_id INTEGER,
                transaction_type TEXT NULL,
                purchase_date TEXT NULL,
                vendor_id INTEGER NULL,
                vendor_name TEXT NULL,
                po_number TEXT NULL,
                account_code TEXT NULL,
                description TEXT NULL,
                expenditure_amount TEXT DEFAULT '0.00',
                encumbrance_amount TEXT DEFAULT '0.00',
                budget_amount TEXT DEFAULT '0.00',
                source_identifier TEXT NULL,
                raw_json TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_budget_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiscal_year TEXT NOT NULL,
                combined_code TEXT NOT NULL,
                fund_code TEXT NULL,
                fund_title TEXT NULL,
                function_code TEXT NULL,
                function_title TEXT NULL,
                building_code TEXT NULL,
                building_title TEXT NULL,
                program_code TEXT NULL,
                program_title TEXT NULL,
                modifier_code TEXT NULL,
                modifier_title TEXT NULL,
                segment_6_code TEXT NULL,
                segment_6_title TEXT NULL,
                description TEXT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(fiscal_year, combined_code)
            );

            CREATE TABLE IF NOT EXISTS finance_budget_buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_code TEXT NOT NULL UNIQUE,
                short_name TEXT NOT NULL,
                full_name TEXT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_budget_building_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_code TEXT NOT NULL,
                alias TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(building_code, alias)
            );

            CREATE INDEX IF NOT EXISTS idx_finance_budget_definitions_combined
            ON finance_budget_definitions(fiscal_year, combined_code);

            CREATE INDEX IF NOT EXISTS idx_finance_budget_definitions_segments
            ON finance_budget_definitions(
                fiscal_year,
                fund_code,
                function_code,
                building_code,
                program_code,
                modifier_code
            );

            CREATE TABLE IF NOT EXISTS finance_fiscal_years (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                short_code TEXT NULL,
                year_number INTEGER NOT NULL,
                friendly_name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                adopted_budget TEXT NOT NULL DEFAULT '0.00',
                status TEXT NOT NULL DEFAULT 'planning',
                is_current INTEGER NOT NULL DEFAULT 0,
                is_next INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finance_fiscal_year_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiscal_year_id INTEGER NOT NULL,
                alias TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(fiscal_year_id, alias)
            );

            CREATE TABLE IF NOT EXISTS finance_fiscal_year_checklist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiscal_year_id INTEGER NOT NULL,
                checklist_type TEXT NOT NULL,
                item_key TEXT NOT NULL,
                label TEXT NOT NULL,
                description TEXT NULL,
                is_required INTEGER NOT NULL DEFAULT 1,
                is_skippable INTEGER NOT NULL DEFAULT 0,
                is_complete INTEGER NOT NULL DEFAULT 0,
                is_skipped INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT NULL,
                completed_by_user_id INTEGER NULL,
                skipped_at TEXT NULL,
                skipped_by_user_id INTEGER NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(fiscal_year_id, checklist_type, item_key)
            );

            CREATE INDEX IF NOT EXISTS idx_finance_fiscal_years_status
            ON finance_fiscal_years(status, is_current, is_next);

            CREATE INDEX IF NOT EXISTS idx_finance_fiscal_year_aliases_alias
            ON finance_fiscal_year_aliases(alias);

            CREATE INDEX IF NOT EXISTS idx_finance_fiscal_year_checklist
            ON finance_fiscal_year_checklist_items(fiscal_year_id, checklist_type);

            CREATE INDEX IF NOT EXISTS idx_finance_attachments_record
            ON finance_attachments(finance_record_id, uploaded_at DESC);

            CREATE INDEX IF NOT EXISTS idx_finance_scope_lookup
            ON finance_user_department_scope(user_id, department_name, area_key, scope_level);

            CREATE INDEX IF NOT EXISTS idx_finance_records_department
            ON finance_records(department_name, record_type, renewal_date, status);

            CREATE INDEX IF NOT EXISTS idx_finance_records_vendor
            ON finance_records(vendor_id, title);

            CREATE INDEX IF NOT EXISTS idx_finance_history_record
            ON finance_record_history(finance_record_id, changed_at);
            """
        )

        now = datetime.now(timezone.utc).isoformat()

        _ensure_column(conn, "finance_fiscal_years", "adopted_budget", "TEXT NOT NULL DEFAULT '0.00'")
        _ensure_column(conn, "finance_fiscal_years", "is_previous", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "finance_fiscal_years", "department_name", "TEXT NULL")
        _ensure_column(conn, "finance_departments", "finance_enabled", "INTEGER NOT NULL DEFAULT 1")

        starter_categories = [
            "Curriculum Software",
            "Maintenance Software",
            "Productivity Software",
            "Security Software",
            "Subscription",
            "Service Agreement",
            "Maintenance Agreement",
            "Student Devices",
            "Staff Devices",
            "Networking Hardware",
            "Printing",
            "Infrastructure",
            "Classroom Technology",
            "Peripherals",
            "Professional Services",
            "Other",
        ]

        for sort_order, category_name in enumerate(starter_categories, start=1):
            conn.execute(
                """
                INSERT OR IGNORE INTO finance_categories (
                    category_name,
                    is_active,
                    sort_order,
                    created_at,
                    updated_at
                )
                VALUES (?, 1, ?, ?, ?)
                """,
                (category_name, sort_order, now, now),
            )

        finance_record_columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(finance_records)").fetchall()
        ]

        if "use_purchase_date_as_start" not in finance_record_columns:
            conn.execute(
                "ALTER TABLE finance_records ADD COLUMN use_purchase_date_as_start INTEGER NOT NULL DEFAULT 1"
            )

        if "term_length" not in finance_record_columns:
            conn.execute(
                "ALTER TABLE finance_records ADD COLUMN term_length INTEGER NULL"
            )

        if "term_unit" not in finance_record_columns:
            conn.execute(
                "ALTER TABLE finance_records ADD COLUMN term_unit TEXT NULL"
            )

        finance_record_columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(finance_records)").fetchall()
        ]

        if "deleted_at" not in finance_record_columns:
            conn.execute(
                "ALTER TABLE finance_records ADD COLUMN deleted_at TEXT NULL"
            )

        finance_vendor_columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(finance_vendors)").fetchall()
        ]

        if "status" not in finance_vendor_columns:
            conn.execute(
                "ALTER TABLE finance_vendors ADD COLUMN status TEXT DEFAULT 'active'"
            )

        if "deleted_at" not in finance_vendor_columns:
            conn.execute(
                "ALTER TABLE finance_vendors ADD COLUMN deleted_at TEXT NULL"
            )

        conn.commit()
