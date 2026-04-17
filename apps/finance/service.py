from datetime import datetime, timezone
from modules.core.identity.identity_db import get_connection as get_identity_connection
from .db import get_connection
import os
import secrets
from pathlib import Path
import csv
from io import TextIOWrapper
from openpyxl import load_workbook

BASE_DIR = Path(__file__).resolve().parents[2]
FINANCE_UPLOADS_DIR = BASE_DIR / "instance" / "finance" / "uploads"
FINANCE_IMPORTS_DIR = BASE_DIR / "instance" / "finance" / "imports"

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def ensure_finance_imports_dir():
    FINANCE_IMPORTS_DIR.mkdir(parents=True, exist_ok=True)

def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def ensure_finance_department(department_name: str) -> dict:
    department_name = normalize_text(department_name)
    if not department_name:
        raise ValueError("department_name is required")

    now = utc_now_iso()

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM finance_departments
            WHERE department_name = ?
            """,
            (department_name,),
        ).fetchone()

        if existing:
            return dict(existing)

        conn.execute(
            """
            INSERT INTO finance_departments (
                department_name,
                is_enabled,
                created_at,
                updated_at
            )
            VALUES (?, 1, ?, ?)
            """,
            (department_name, now, now),
        )
        conn.commit()

        row = conn.execute(
            """
            SELECT *
            FROM finance_departments
            WHERE department_name = ?
            """,
            (department_name,),
        ).fetchone()

    return dict(row)


def list_active_departments_from_users() -> list[str]:
    with get_identity_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT TRIM(department) AS department_name
            FROM users
            WHERE is_active = 1
              AND department IS NOT NULL
              AND TRIM(department) <> ''
            ORDER BY department_name COLLATE NOCASE
            """
        ).fetchall()

    return [row["department_name"] for row in rows if row["department_name"]]


def sync_departments_from_users() -> list[dict]:
    for department_name in list_active_departments_from_users():
        ensure_finance_department(department_name)

    return list_enabled_departments()


def list_enabled_departments() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_departments
            WHERE is_enabled = 1
            ORDER BY department_name COLLATE NOCASE
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_department_record(department_name: str) -> dict | None:
    department_name = normalize_text(department_name)
    if not department_name:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM finance_departments
            WHERE department_name = ?
            """
            ,
            (department_name,),
        ).fetchone()

    return dict(row) if row else None


def list_vendors() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_vendors
            WHERE is_active = 1
            ORDER BY vendor_name COLLATE NOCASE
            """
        ).fetchall()

    return [dict(row) for row in rows]

def list_records_for_vendor(vendor_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                c.category_name
            FROM finance_records r
            LEFT JOIN finance_categories c ON c.id = r.category_id
            WHERE r.vendor_id = ?
            ORDER BY
                CASE WHEN r.renewal_date IS NULL THEN 1 ELSE 0 END,
                r.renewal_date ASC,
                r.title COLLATE NOCASE ASC
            """,
            (vendor_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def list_active_vendors() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_vendors
            WHERE status IS NULL OR status NOT IN ('archived', 'deleted')
            ORDER BY vendor_name COLLATE NOCASE ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def list_archived_vendors() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_vendors
            WHERE status = 'archived'
            ORDER BY vendor_name COLLATE NOCASE ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def list_deleted_vendors() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_vendors
            WHERE status = 'deleted'
            ORDER BY deleted_at DESC, vendor_name COLLATE NOCASE ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def archive_vendor(vendor_id: int) -> bool:
    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        return False

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_vendors
            SET
                status = 'archived',
                is_active = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (now, vendor_id),
        )
        conn.commit()

    return True


def delete_vendor(vendor_id: int) -> bool:
    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        return False

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_vendors
            SET
                status = 'deleted',
                deleted_at = ?,
                is_active = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, vendor_id),
        )
        conn.commit()

    return True


def restore_vendor(vendor_id: int) -> bool:
    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        return False

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_vendors
            SET
                status = 'active',
                deleted_at = NULL,
                is_active = 1,
                updated_at = ?
            WHERE id = ?
            """,
            (now, vendor_id),
        )
        conn.commit()

    return True


def list_categories() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_categories
            WHERE is_active = 1
            ORDER BY sort_order, category_name COLLATE NOCASE
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_finance_dashboard_summary(department_name: str) -> dict:
    department_name = normalize_text(department_name)
    if not department_name:
        return {
            "total_records": 0,
            "renewals_due_30": 0,
            "active_vendors": 0,
        }

    with get_connection() as conn:
        total_records = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM finance_records
            WHERE department_name = ?
              AND status NOT IN ('archived', 'deleted')
            """,
            (department_name,),
        ).fetchone()["count"]

        renewals_due_30 = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM finance_records
            WHERE department_name = ?
              AND renewal_date IS NOT NULL
              AND status IN ('active', 'pending_renewal')
              AND DATE(renewal_date) <= DATE('now', '+30 day')
            """,
            (department_name,),
        ).fetchone()["count"]

        active_vendors = conn.execute(
            """
            SELECT COUNT(DISTINCT vendor_id) AS count
            FROM finance_records
            WHERE department_name = ?
              AND vendor_id IS NOT NULL
              AND status NOT IN ('archived', 'deleted')
            """,
            (department_name,),
        ).fetchone()["count"]

    return {
        "total_records": total_records,
        "renewals_due_30": renewals_due_30,
        "active_vendors": active_vendors,
    }

def create_record(
    *,
    record_type: str,
    title: str,
    department_name: str,
    vendor_id: int | None = None,
    category_id: int | None = None,
    account_code: str | None = None,
    po_number: str | None = None,
    purchase_date: str | None = None,
    service_start_date: str | None = None,
    use_purchase_date_as_start: bool = True,
    term_length: int | None = None,
    term_unit: str | None = None,
    expiration_date: str | None = None,
    renewal_date: str | None = None,
    notify_days_before: int = 30,
    notification_recipients: str | None = None,
    status: str = "active",
    cost: str | None = None,
    notes: str | None = None,
    created_by_user_id: int | None = None,
) -> int:
    title = normalize_text(title)
    department_name = normalize_text(department_name)
    record_type = normalize_text(record_type) or "renewal"
    status = normalize_text(status) or "active"

    if not title:
        raise ValueError("title is required")
    if not department_name:
        raise ValueError("department_name is required")

    now = utc_now_iso()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO finance_records (
                record_type,
                title,
                vendor_id,
                category_id,
                department_name,
                account_code,
                po_number,
                purchase_date,
                service_start_date,
                use_purchase_date_as_start,
                term_length,
                term_unit,
                expiration_date,
                renewal_date,
                notify_days_before,
                notification_recipients,
                status,
                cost,
                notes,
                created_by_user_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_type,
                title,
                vendor_id,
                category_id,
                department_name,
                normalize_text(account_code),
                normalize_text(po_number),
                normalize_text(purchase_date),
                normalize_text(service_start_date),
                1 if use_purchase_date_as_start else 0,
                term_length,
                normalize_text(term_unit),
                normalize_text(expiration_date),
                normalize_text(renewal_date),
                notify_days_before or 30,
                normalize_text(notification_recipients),
                status,
                normalize_text(cost),
                normalize_text(notes),
                created_by_user_id,
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO finance_record_history (
                finance_record_id,
                event_type,
                summary,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, 'created', ?, ?, ?)
            """,
            (
                record_id,
                f"Record created: {title}",
                created_by_user_id,
                now,
            ),
        )

        conn.commit()
        return record_id
    

def list_records_for_department(department_name: str) -> list[dict]:
    department_name = normalize_text(department_name)
    if not department_name:
        return []

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                v.vendor_name,
                c.category_name
            FROM finance_records r
            LEFT JOIN finance_vendors v ON v.id = r.vendor_id
            LEFT JOIN finance_categories c ON c.id = r.category_id
            WHERE r.department_name = ?
            ORDER BY
                CASE WHEN r.renewal_date IS NULL THEN 1 ELSE 0 END,
                r.renewal_date ASC,
                r.title COLLATE NOCASE ASC
            """,
            (department_name,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_record_by_id(record_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                r.*,
                v.vendor_name,
                c.category_name
            FROM finance_records r
            LEFT JOIN finance_vendors v ON v.id = r.vendor_id
            LEFT JOIN finance_categories c ON c.id = r.category_id
            WHERE r.id = ?
            """,
            (record_id,),
        ).fetchone()

    return dict(row) if row else None

def create_vendor(
    vendor_name: str,
    vendor_code: str | None = None,
    website: str | None = None,
    main_phone: str | None = None,
    billing_email: str | None = None,
    support_email: str | None = None,
    sales_contact_name: str | None = None,
    sales_contact_email: str | None = None,
    notes: str | None = None,
) -> int:
    vendor_name = normalize_text(vendor_name)
    if not vendor_name:
        raise ValueError("vendor_name is required")

    now = utc_now_iso()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO finance_vendors (
                vendor_name,
                vendor_code,
                website,
                main_phone,
                billing_email,
                support_email,
                sales_contact_name,
                sales_contact_email,
                is_active,
                status,
                notes,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, ?)
            """,
            (
                vendor_name,
                normalize_text(vendor_code),
                normalize_text(website),
                normalize_text(main_phone),
                normalize_text(billing_email),
                normalize_text(support_email),
                normalize_text(sales_contact_name),
                normalize_text(sales_contact_email),
                normalize_text(notes),
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_vendor(
    vendor_id: int,
    vendor_name: str,
    vendor_code: str | None = None,
    website: str | None = None,
    main_phone: str | None = None,
    billing_email: str | None = None,
    support_email: str | None = None,
    sales_contact_name: str | None = None,
    sales_contact_email: str | None = None,
    status: str = "active",
    notes: str | None = None,
):
    vendor_name = normalize_text(vendor_name)
    if not vendor_name:
        raise ValueError("vendor_name is required")

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_vendors
            SET
                vendor_name = ?,
                vendor_code = ?,
                website = ?,
                main_phone = ?,
                billing_email = ?,
                support_email = ?,
                sales_contact_name = ?,
                sales_contact_email = ?,
                is_active = ?,
                status = ?,
                notes = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                vendor_name,
                normalize_text(vendor_code),
                normalize_text(website),
                normalize_text(main_phone),
                normalize_text(billing_email),
                normalize_text(support_email),
                normalize_text(sales_contact_name),
                normalize_text(sales_contact_email),
                1 if status == "active" else 0,
                normalize_text(status) or "active",
                normalize_text(notes),
                now,
                vendor_id,
            ),
        )
        conn.commit()


def get_vendor_by_id(vendor_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM finance_vendors
            WHERE id = ?
            """,
            (vendor_id,),
        ).fetchone()

    return dict(row) if row else None


def list_vendors_all() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_vendors
            ORDER BY vendor_name COLLATE NOCASE
            """
        ).fetchall()

    return [dict(row) for row in rows]



def update_record(
    *,
    record_id: int,
    record_type: str,
    title: str,
    department_name: str,
    vendor_id: int | None = None,
    category_id: int | None = None,
    account_code: str | None = None,
    po_number: str | None = None,
    purchase_date: str | None = None,
    service_start_date: str | None = None,
    use_purchase_date_as_start: bool = True,
    term_length: int | None = None,
    term_unit: str | None = None,
    expiration_date: str | None = None,
    renewal_date: str | None = None,
    notify_days_before: int = 30,
    notification_recipients: str | None = None,
    status: str = "active",
    cost: str | None = None,
    notes: str | None = None,
    changed_by_user_id: int | None = None,
):
    title = normalize_text(title)
    department_name = normalize_text(department_name)
    record_type = normalize_text(record_type) or "renewal"
    status = normalize_text(status) or "active"

    if not title:
        raise ValueError("title is required")
    if not department_name:
        raise ValueError("department_name is required")

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_records
            SET
                record_type = ?,
                title = ?,
                vendor_id = ?,
                category_id = ?,
                department_name = ?,
                account_code = ?,
                po_number = ?,
                purchase_date = ?,
                service_start_date = ?,
                use_purchase_date_as_start = ?,
                term_length = ?,
                term_unit = ?,
                expiration_date = ?,
                renewal_date = ?,
                notify_days_before = ?,
                notification_recipients = ?,
                status = ?,
                cost = ?,
                notes = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                record_type,
                title,
                vendor_id,
                category_id,
                department_name,
                normalize_text(account_code),
                normalize_text(po_number),
                normalize_text(purchase_date),
                normalize_text(service_start_date),
                1 if use_purchase_date_as_start else 0,
                term_length,
                normalize_text(term_unit),
                normalize_text(expiration_date),
                normalize_text(renewal_date),
                notify_days_before or 30,
                normalize_text(notification_recipients),
                status,
                normalize_text(cost),
                normalize_text(notes),
                now,
                record_id,
            ),
        )

        conn.execute(
            """
            INSERT INTO finance_record_history (
                finance_record_id,
                event_type,
                summary,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, 'updated', ?, ?, ?)
            """,
            (
                record_id,
                f"Record updated: {title}",
                changed_by_user_id,
                now,
            ),
        )

        conn.commit()

def ensure_finance_uploads_dir():
    FINANCE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def list_attachments_for_record(record_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_attachments
            WHERE finance_record_id = ?
            ORDER BY uploaded_at DESC, id DESC
            """,
            (record_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_attachment_by_id(attachment_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM finance_attachments
            WHERE id = ?
            """,
            (attachment_id,),
        ).fetchone()

    return dict(row) if row else None


ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".csv",
    ".xml",
    ".txt",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

def save_attachment(
    *,
    finance_record_id: int,
    original_filename: str,
    file_bytes: bytes,
    mime_type: str,
    document_type: str = "other",
    uploaded_by_user_id: int | None = None,
) -> int:
    if not original_filename:
        raise ValueError("original_filename is required")
    if not file_bytes:
        raise ValueError("file_bytes is required")

    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValueError(
            "Unsupported attachment type. Allowed types: "
            "PDF, CSV, XML, TXT, DOC, DOCX, XLS, XLSX, JPG, JPEG, PNG, WEBP."
        )

    ensure_finance_uploads_dir()

    stored_name = f"{secrets.token_hex(16)}{suffix}"
    stored_path = FINANCE_UPLOADS_DIR / stored_name

    with open(stored_path, "wb") as f:
        f.write(file_bytes)

    now = utc_now_iso()
    file_size = len(file_bytes)

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO finance_attachments (
                finance_record_id,
                file_name,
                stored_name,
                mime_type,
                file_size,
                document_type,
                uploaded_by_user_id,
                uploaded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finance_record_id,
                original_filename,
                stored_name,
                mime_type or "application/octet-stream",
                file_size,
                normalize_text(document_type) or "other",
                uploaded_by_user_id,
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO finance_record_history (
                finance_record_id,
                event_type,
                summary,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, 'attachment_added', ?, ?, ?)
            """,
            (
                finance_record_id,
                f"Attachment added: {original_filename}",
                uploaded_by_user_id,
                now,
            ),
        )

        conn.commit()
        return cursor.lastrowid
    
def delete_attachment(attachment_id: int, deleted_by_user_id: int | None = None) -> bool:
    attachment = get_attachment_by_id(attachment_id)
    if not attachment:
        return False

    file_path = FINANCE_UPLOADS_DIR / attachment["stored_name"]
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM finance_attachments
            WHERE id = ?
            """,
            (attachment_id,),
        )

        conn.execute(
            """
            INSERT INTO finance_record_history (
                finance_record_id,
                event_type,
                summary,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, 'attachment_deleted', ?, ?, ?)
            """,
            (
                attachment["finance_record_id"],
                f"Attachment deleted: {attachment['file_name']}",
                deleted_by_user_id,
                now,
            ),
        )

        conn.commit()

    if file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            pass

    return True

def list_history_for_record(record_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_record_history
            WHERE finance_record_id = ?
            ORDER BY changed_at DESC, id DESC
            """,
            (record_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def archive_record(record_id: int, changed_by_user_id: int | None = None) -> bool:
    record = get_record_by_id(record_id)
    if not record:
        return False

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_records
            SET
                status = 'archived',
                updated_at = ?
            WHERE id = ?
            """,
            (now, record_id),
        )

        conn.execute(
            """
            INSERT INTO finance_record_history (
                finance_record_id,
                event_type,
                summary,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, 'archived', ?, ?, ?)
            """,
            (
                record_id,
                f"Record archived: {record['title']}",
                changed_by_user_id,
                now,
            ),
        )

        conn.commit()

    return True


def delete_record(record_id: int, deleted_by_user_id: int | None = None) -> bool:
    record = get_record_by_id(record_id)
    if not record:
        return False

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_records
            SET
                status = 'deleted',
                deleted_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, record_id),
        )

        conn.execute(
            """
            INSERT INTO finance_record_history (
                finance_record_id,
                event_type,
                summary,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, 'deleted', ?, ?, ?)
            """,
            (
                record_id,
                f"Record moved to deleted: {record['title']}",
                deleted_by_user_id,
                now,
            ),
        )

        conn.commit()

    return True

def list_active_records_for_department(department_name: str) -> list[dict]:
    department_name = normalize_text(department_name)
    if not department_name:
        return []

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                v.vendor_name,
                c.category_name
            FROM finance_records r
            LEFT JOIN finance_vendors v ON v.id = r.vendor_id
            LEFT JOIN finance_categories c ON c.id = r.category_id
            WHERE r.department_name = ?
              AND r.status NOT IN ('archived', 'deleted')
            ORDER BY
                CASE WHEN r.renewal_date IS NULL THEN 1 ELSE 0 END,
                r.renewal_date ASC,
                r.title COLLATE NOCASE ASC
            """,
            (department_name,),
        ).fetchall()

    return [dict(row) for row in rows]

def list_archived_records_for_department(department_name: str) -> list[dict]:
    department_name = normalize_text(department_name)
    if not department_name:
        return []

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                v.vendor_name,
                c.category_name
            FROM finance_records r
            LEFT JOIN finance_vendors v ON v.id = r.vendor_id
            LEFT JOIN finance_categories c ON c.id = r.category_id
            WHERE r.department_name = ?
              AND r.status = 'archived'
            ORDER BY r.updated_at DESC, r.title COLLATE NOCASE ASC
            """,
            (department_name,),
        ).fetchall()

    return [dict(row) for row in rows]

def list_deleted_records_for_department(department_name: str) -> list[dict]:
    department_name = normalize_text(department_name)
    if not department_name:
        return []

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                v.vendor_name,
                c.category_name
            FROM finance_records r
            LEFT JOIN finance_vendors v ON v.id = r.vendor_id
            LEFT JOIN finance_categories c ON c.id = r.category_id
            WHERE r.department_name = ?
              AND r.status = 'deleted'
            ORDER BY r.deleted_at DESC, r.title COLLATE NOCASE ASC
            """,
            (department_name,),
        ).fetchall()

    return [dict(row) for row in rows]

def restore_archived_record(record_id: int, changed_by_user_id: int | None = None) -> bool:
    record = get_record_by_id(record_id)
    if not record:
        return False

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_records
            SET
                status = 'active',
                updated_at = ?
            WHERE id = ?
            """,
            (now, record_id),
        )

        conn.execute(
            """
            INSERT INTO finance_record_history (
                finance_record_id,
                event_type,
                summary,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, 'restored', ?, ?, ?)
            """,
            (
                record_id,
                f"Archived record restored: {record['title']}",
                changed_by_user_id,
                now,
            ),
        )

        conn.commit()

    return True

def restore_deleted_record(record_id: int, changed_by_user_id: int | None = None) -> bool:
    record = get_record_by_id(record_id)
    if not record:
        return False

    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_records
            SET
                status = 'active',
                deleted_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now, record_id),
        )

        conn.execute(
            """
            INSERT INTO finance_record_history (
                finance_record_id,
                event_type,
                summary,
                changed_by_user_id,
                changed_at
            )
            VALUES (?, 'restored', ?, ?, ?)
            """,
            (
                record_id,
                f"Deleted record restored: {record['title']}",
                changed_by_user_id,
                now,
            ),
        )

        conn.commit()

    return True

def purge_deleted_records_older_than(days: int = 30) -> int:
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id
            FROM finance_records
            WHERE status = 'deleted'
              AND deleted_at IS NOT NULL
              AND DATETIME(deleted_at) <= DATETIME('now', '-{int(days)} day')
            """
        ).fetchall()

    record_ids = [row["id"] for row in rows]
    if not record_ids:
        return 0

    purged_count = 0

    for record_id in record_ids:
        record = get_record_by_id(record_id)
        if not record:
            continue

        attachments = list_attachments_for_record(record_id)

        with get_connection() as conn:
            conn.execute(
                "DELETE FROM finance_attachments WHERE finance_record_id = ?",
                (record_id,),
            )
            conn.execute(
                "DELETE FROM finance_record_history WHERE finance_record_id = ?",
                (record_id,),
            )
            conn.execute(
                "DELETE FROM finance_records WHERE id = ?",
                (record_id,),
            )
            conn.commit()

        for attachment in attachments:
            file_path = FINANCE_UPLOADS_DIR / attachment["stored_name"]
            if file_path.exists():
                try:
                    file_path.unlink()
                except OSError:
                    pass

        purged_count += 1

    return purged_count

def get_vendor_department_context(
    *,
    user_departments: list[dict],
    vendor_id: int,
    posted_department_name: str | None = None,
) -> str | None:
    posted_department_name = normalize_text(posted_department_name)
    if posted_department_name:
        return posted_department_name

    related_records = list_records_for_vendor(vendor_id)
    if related_records:
        return related_records[0]["department_name"]

    if user_departments:
        return user_departments[0]["department_name"]

    return None

def list_import_profiles() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_import_profiles
            WHERE SUBSTR(profile_name, 1, 5) <> '_run_'
            ORDER BY profile_name COLLATE NOCASE
            """
        ).fetchall()

    return [dict(row) for row in rows]


def list_import_runs(limit: int = 25) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_import_runs
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def list_import_sources() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_import_sources
            ORDER BY source_name COLLATE NOCASE
            """
        ).fetchall()

    return [dict(row) for row in rows]

def create_import_run(
    *,
    import_type: str,
    source_type: str,
    profile_id: int | None = None,
    original_filename: str | None = None,
    stored_filename: str | None = None,
    status: str = "pending",
    started_by_user_id: int | None = None,
) -> int:
    now = utc_now_iso()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO finance_import_runs (
                import_type,
                source_type,
                profile_id,
                original_filename,
                stored_filename,
                status,
                started_by_user_id,
                started_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalize_text(import_type),
                normalize_text(source_type),
                profile_id,
                normalize_text(original_filename),
                normalize_text(stored_filename),
                normalize_text(status) or "pending",
                started_by_user_id,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    
def get_import_run_by_id(run_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM finance_import_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()

    return dict(row) if row else None

def update_import_run_status(
    run_id: int,
    *,
    status: str,
    total_rows: int | None = None,
    run_notes: str | None = None,
    completed: bool = False,
):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_import_runs
            SET
                status = ?,
                total_rows = COALESCE(?, total_rows),
                run_notes = COALESCE(?, run_notes),
                completed_at = CASE WHEN ? THEN ? ELSE completed_at END
            WHERE id = ?
            """,
            (
                normalize_text(status) or "pending",
                total_rows,
                normalize_text(run_notes),
                1 if completed else 0,
                now,
                run_id,
            ),
        )
        conn.commit()

def save_import_upload(original_filename: str, file_bytes: bytes) -> str:
    if not original_filename:
        raise ValueError("original_filename is required")
    if not file_bytes:
        raise ValueError("file_bytes is required")

    ensure_finance_imports_dir()

    ext = Path(original_filename).suffix.lower()
    stored_name = f"{secrets.token_hex(16)}{ext}"
    stored_path = FINANCE_IMPORTS_DIR / stored_name

    with open(stored_path, "wb") as f:
        f.write(file_bytes)

    return stored_name

def read_import_headers(stored_filename: str) -> list[str]:
    if not stored_filename:
        raise ValueError("stored_filename is required")

    file_path = FINANCE_IMPORTS_DIR / stored_filename
    if not file_path.exists():
        raise FileNotFoundError(f"Import file not found: {stored_filename}")

    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        with open(file_path, "rb") as raw_file:
            text_file = TextIOWrapper(raw_file, encoding="utf-8-sig", newline="")
            reader = csv.reader(text_file)
            headers = next(reader, [])
            return [str(h).strip() for h in headers if str(h).strip()]

    if suffix == ".xlsx":
        workbook = load_workbook(filename=file_path, read_only=True, data_only=True)
        sheet = workbook.active
        first_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), [])
        return [str(h).strip() for h in first_row if h is not None and str(h).strip()]

    raise ValueError("Unsupported file type. Only CSV and XLSX are supported.")

def get_import_target_fields(import_type: str) -> list[dict]:
    import_type = (import_type or "").strip().lower()

    if import_type == "vendors":
        return [
            {"field_name": "vendor_name", "label": "Vendor Name", "required": True},
            {"field_name": "vendor_code", "label": "Vendor Code", "required": False},
            {"field_name": "website", "label": "Website", "required": False},
            {"field_name": "main_phone", "label": "Main Phone", "required": False},
            {"field_name": "billing_email", "label": "Billing Email", "required": False},
            {"field_name": "support_email", "label": "Support Email", "required": False},
            {"field_name": "sales_contact_name", "label": "Sales Contact Name", "required": False},
            {"field_name": "sales_contact_email", "label": "Sales Contact Email", "required": False},
            {"field_name": "notes", "label": "Notes", "required": False},
        ]

    return [
        {"field_name": "title", "label": "Item / Service Name", "required": True},
        {"field_name": "record_type", "label": "Record Type", "required": False},
        {"field_name": "vendor_name", "label": "Vendor Name", "required": False},
        {"field_name": "vendor_code", "label": "Vendor Code", "required": False},
        {"field_name": "category_name", "label": "Category", "required": False},
        {"field_name": "account_code", "label": "Account Code", "required": False},
        {"field_name": "po_number", "label": "PO Number", "required": False},
        {"field_name": "purchase_date", "label": "Purchase Date", "required": False},
        {"field_name": "service_start_date", "label": "Service Start Date", "required": False},
        {"field_name": "term_length", "label": "Term Length", "required": False},
        {"field_name": "term_unit", "label": "Term Unit", "required": False},
        {"field_name": "expiration_date", "label": "Expiration Date", "required": False},
        {"field_name": "renewal_date", "label": "Renewal Date", "required": False},
        {"field_name": "notify_days_before", "label": "Notify Days Before", "required": False},
        {"field_name": "notification_recipients", "label": "Notification Recipients", "required": False},
        {"field_name": "status", "label": "Status", "required": False},
        {"field_name": "cost", "label": "Cost", "required": False},
        {"field_name": "notes", "label": "Notes", "required": False},
    ]

def replace_import_profile_fields(profile_id: int, field_mappings: list[dict]):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            "DELETE FROM finance_import_profile_fields WHERE profile_id = ?",
            (profile_id,),
        )

        for item in field_mappings:
            ignore_field = 1 if item.get("ignore_field") else 0
            source_column_name = None if ignore_field else normalize_text(item.get("source_column_name"))

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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    source_column_name,
                    normalize_text(item.get("target_field_name")),
                    normalize_text(item.get("transform_rule")),
                    normalize_text(item.get("default_value")),
                    1 if item.get("required") else 0,
                    ignore_field,
                    now,
                    now,
                ),
            )

        conn.commit()

def create_import_profile(
    *,
    profile_name: str,
    source_type: str,
    target_area: str,
    description: str | None = None,
    created_by_user_id: int | None = None,
) -> int:
    profile_name = normalize_text(profile_name)
    source_type = normalize_text(source_type)
    target_area = normalize_text(target_area)

    if not profile_name:
        raise ValueError("profile_name is required")
    if not source_type:
        raise ValueError("source_type is required")
    if not target_area:
        raise ValueError("target_area is required")

    now = utc_now_iso()

    with get_connection() as conn:
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
            VALUES (?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                profile_name,
                source_type,
                target_area,
                normalize_text(description),
                created_by_user_id,
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    
def get_vendor_template_headers() -> list[str]:
    return [
        "vendor_name",
        "vendor_code",
        "website",
        "main_phone",
        "billing_email",
        "support_email",
        "sales_contact_name",
        "sales_contact_email",
        "notes",
    ]

def get_record_template_headers() -> list[str]:
    return [
        "title",
        "record_type",
        "vendor_name",
        "vendor_code",
        "category_name",
        "account_code",
        "po_number",
        "purchase_date",
        "service_start_date",
        "term_length",
        "term_unit",
        "expiration_date",
        "renewal_date",
        "notify_days_before",
        "notification_recipients",
        "status",
        "cost",
        "notes",
    ]

def get_import_profile_by_name(profile_name: str) -> dict | None:
    profile_name = normalize_text(profile_name)
    if not profile_name:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM finance_import_profiles
            WHERE profile_name = ?
            """,
            (profile_name,),
        ).fetchone()

    return dict(row) if row else None

def get_import_profile_fields(profile_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_import_profile_fields
            WHERE profile_id = ?
            ORDER BY id ASC
            """,
            (profile_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def set_import_run_profile(run_id: int, profile_id: int):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_import_runs
            SET profile_id = ?
            WHERE id = ?
            """,
            (profile_id, run_id),
        )
        conn.commit()


def log_import_run_error(
    *,
    run_id: int,
    row_number: int | None,
    source_identifier: str | None,
    error_message: str,
):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO finance_import_run_errors (
                run_id,
                row_number,
                source_identifier,
                error_message,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                row_number,
                normalize_text(source_identifier),
                error_message,
                now,
            ),
        )
        conn.commit()


def list_import_run_errors(run_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_import_run_errors
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def update_import_run_results(
    run_id: int,
    *,
    status: str,
    total_rows: int,
    created_rows: int,
    updated_rows: int,
    skipped_rows: int,
    error_rows: int,
    run_notes: str | None = None,
    completed: bool = False,
):
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE finance_import_runs
            SET
                status = ?,
                total_rows = ?,
                created_rows = ?,
                updated_rows = ?,
                skipped_rows = ?,
                error_rows = ?,
                run_notes = ?,
                completed_at = CASE WHEN ? THEN ? ELSE completed_at END
            WHERE id = ?
            """,
            (
                normalize_text(status) or "pending",
                total_rows,
                created_rows,
                updated_rows,
                skipped_rows,
                error_rows,
                normalize_text(run_notes),
                1 if completed else 0,
                now,
                run_id,
            ),
        )
        conn.commit()


def read_import_rows(stored_filename: str) -> list[dict]:
    if not stored_filename:
        raise ValueError("stored_filename is required")

    file_path = FINANCE_IMPORTS_DIR / stored_filename
    if not file_path.exists():
        raise FileNotFoundError(f"Import file not found: {stored_filename}")

    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        with open(file_path, "rb") as raw_file:
            text_file = TextIOWrapper(raw_file, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text_file)
            return [
                {str(k).strip(): ("" if v is None else str(v).strip()) for k, v in row.items()}
                for row in reader
            ]

    if suffix == ".xlsx":
        workbook = load_workbook(filename=file_path, read_only=True, data_only=True)
        sheet = workbook.active

        rows_iter = sheet.iter_rows(values_only=True)
        headers = next(rows_iter, None)
        if not headers:
            return []

        header_names = [str(h).strip() if h is not None else "" for h in headers]

        results = []
        for row in rows_iter:
            item = {}
            for idx, header in enumerate(header_names):
                if not header:
                    continue
                value = row[idx] if idx < len(row) else None
                item[header] = "" if value is None else str(value).strip()
            results.append(item)

        return results

    raise ValueError("Unsupported file type. Only CSV and XLSX are supported.")


def preview_import_rows(
    *,
    run_id: int,
    profile_id: int,
    limit: int = 10,
) -> list[dict]:
    run = get_import_run_by_id(run_id)
    if not run:
        raise ValueError("Import run not found")

    rows = read_import_rows(run["stored_filename"])
    mappings = get_import_profile_fields(profile_id)

    target_to_source = {}
    for mapping in mappings:
        if mapping["ignore_field"]:
            continue
        if not mapping["source_column_name"]:
            continue
        target_to_source[mapping["target_field_name"]] = mapping["source_column_name"]

    preview = []
    for row in rows[:limit]:
        mapped = {}
        for target_field, source_column in target_to_source.items():
            mapped[target_field] = row.get(source_column, "")
        preview.append(mapped)

    return preview


def find_vendor_for_import(vendor_name: str | None = None, vendor_code: str | None = None) -> dict | None:
    vendor_name = normalize_text(vendor_name)
    vendor_code = normalize_text(vendor_code)

    with get_connection() as conn:
        if vendor_code:
            row = conn.execute(
                """
                SELECT *
                FROM finance_vendors
                WHERE vendor_code = ?
                LIMIT 1
                """,
                (vendor_code,),
            ).fetchone()
            if row:
                return dict(row)

        if vendor_name:
            row = conn.execute(
                """
                SELECT *
                FROM finance_vendors
                WHERE LOWER(TRIM(vendor_name)) = LOWER(TRIM(?))
                LIMIT 1
                """,
                (vendor_name,),
            ).fetchone()
            if row:
                return dict(row)

    return None


def get_or_create_vendor_for_import(
    *,
    vendor_name: str | None = None,
    vendor_code: str | None = None,
) -> tuple[int | None, bool]:
    vendor_name = normalize_text(vendor_name)
    vendor_code = normalize_text(vendor_code)

    if not vendor_name and not vendor_code:
        return None, False

    existing = find_vendor_for_import(vendor_name=vendor_name, vendor_code=vendor_code)
    if existing:
        return existing["id"], False

    if vendor_name:
        vendor_id = create_vendor(
            vendor_name=vendor_name,
            vendor_code=vendor_code,
        )
        return vendor_id, True

    return None, False


def execute_records_import(
    *,
    run_id: int,
    profile_id: int,
    default_department_name: str | None = None,
    created_by_user_id: int | None = None,
) -> dict:
    run = get_import_run_by_id(run_id)
    if not run:
        raise ValueError("Import run not found")

    rows = read_import_rows(run["stored_filename"])
    mappings = get_import_profile_fields(profile_id)

    target_to_source = {}
    required_targets = set()

    for mapping in mappings:
        target_field = mapping["target_field_name"]
        if mapping["required"]:
            required_targets.add(target_field)

        if mapping["ignore_field"]:
            continue
        if not mapping["source_column_name"]:
            continue

        target_to_source[target_field] = mapping["source_column_name"]

    total_rows = len(rows)
    created_rows = 0
    skipped_rows = 0
    error_rows = 0
    vendors_created = 0

    update_import_run_results(
        run_id,
        status="running",
        total_rows=total_rows,
        created_rows=0,
        updated_rows=0,
        skipped_rows=0,
        error_rows=0,
        run_notes="Import execution started.",
        completed=False,
    )

    for index, row in enumerate(rows, start=2):  # row 1 is header
        try:
            mapped = {}
            for target_field, source_column in target_to_source.items():
                mapped[target_field] = normalize_text(row.get(source_column))

            # Default department from current Finance area if not mapped in file
            if default_department_name:
                mapped["department_name"] = normalize_text(default_department_name)

            # Only require title at this stage; department can fall back to default
            missing_required = []
            if not normalize_text(mapped.get("title")):
                missing_required.append("title")

            if missing_required:
                skipped_rows += 1
                log_import_run_error(
                    run_id=run_id,
                    row_number=index,
                    source_identifier=mapped.get("title") or row.get(next(iter(row.keys()), ""), ""),
                    error_message=f"Missing required mapped fields: {', '.join(missing_required)}",
                )
                continue

            vendor_id, vendor_was_created = get_or_create_vendor_for_import(
                vendor_name=mapped.get("vendor_name"),
                vendor_code=mapped.get("vendor_code"),
            )

            if vendor_was_created:
                vendors_created += 1

            term_length = None
            if mapped.get("term_length"):
                try:
                    term_length = int(str(mapped["term_length"]).strip())
                except ValueError:
                    term_length = None

            notify_days_before = 30
            if mapped.get("notify_days_before"):
                try:
                    notify_days_before = int(str(mapped["notify_days_before"]).strip())
                except ValueError:
                    notify_days_before = 30

            print("IMPORT ROW:", mapped)

            create_record(
                record_type=mapped.get("record_type") or "renewal",
                title=mapped.get("title") or "",
                department_name=mapped.get("department_name") or "",
                vendor_id=vendor_id,
                category_id=None,
                account_code=mapped.get("account_code"),
                po_number=mapped.get("po_number"),
                purchase_date=mapped.get("purchase_date"),
                service_start_date=mapped.get("service_start_date"),
                use_purchase_date_as_start=not bool(mapped.get("service_start_date")),
                term_length=term_length,
                term_unit=mapped.get("term_unit"),
                expiration_date=mapped.get("expiration_date"),
                renewal_date=mapped.get("renewal_date"),
                notify_days_before=notify_days_before,
                notification_recipients=mapped.get("notification_recipients"),
                status=mapped.get("status") or "active",
                cost=mapped.get("cost"),
                notes=mapped.get("notes"),
                created_by_user_id=created_by_user_id,
            )

            created_rows += 1

        except Exception as exc:
            print("IMPORT ERROR:", exc)
            error_rows += 1
            log_import_run_error(
                run_id=run_id,
                row_number=index,
                source_identifier=row.get(next(iter(row.keys()), ""), "") if row else None,
                error_message=str(exc),
            )

    run_notes = (
        f"Import completed. Created records: {created_rows}, "
        f"Created vendors: {vendors_created}, "
        f"Skipped: {skipped_rows}, Errors: {error_rows}."
    )

    final_status = "completed"
    if error_rows and not created_rows:
        final_status = "completed_with_errors"
    elif error_rows:
        final_status = "completed_with_warnings"

    update_import_run_results(
        run_id,
        status=final_status,
        total_rows=total_rows,
        created_rows=created_rows,
        updated_rows=0,
        skipped_rows=skipped_rows,
        error_rows=error_rows,
        run_notes=run_notes,
        completed=True,
    )

    return {
        "total_rows": total_rows,
        "created_rows": created_rows,
        "updated_rows": 0,
        "skipped_rows": skipped_rows,
        "error_rows": error_rows,
        "vendors_created": vendors_created,
        "status": final_status,
        "run_notes": run_notes,
    }

def get_import_run_field_map(run_id: int) -> dict[str, str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT target_field_name, source_column_name
            FROM finance_import_profile_fields
            WHERE profile_id = (
                SELECT profile_id
                FROM finance_import_runs
                WHERE id = ?
            )
              AND ignore_field = 0
              AND source_column_name IS NOT NULL
            """,
            (run_id,),
        ).fetchall()

    return {
        row["target_field_name"]: row["source_column_name"]
        for row in rows
    }

def get_import_profile_field_map(profile_id: int) -> dict[str, str]:
    rows = get_import_profile_fields(profile_id)
    result = {}

    for row in rows:
        if row.get("ignore_field"):
            continue

        target_field = row.get("target_field_name")
        source_column = row.get("source_column_name")

        if target_field and source_column:
            result[target_field] = source_column

    return result


def validate_records_import(
    *,
    run_id: int,
    profile_id: int,
    default_department_name: str | None = None,
    preview_limit: int = 20,
) -> dict:
    run = get_import_run_by_id(run_id)
    if not run:
        raise ValueError("Import run not found")

    rows = read_import_rows(run["stored_filename"])
    mappings = get_import_profile_fields(profile_id)

    target_to_source = {}
    for mapping in mappings:
        if mapping["ignore_field"]:
            continue
        if not mapping["source_column_name"]:
            continue
        target_to_source[mapping["target_field_name"]] = mapping["source_column_name"]

    preview_rows = []
    errors = []
    valid_rows = 0
    skipped_rows = 0
    vendors_to_create = 0

    for index, row in enumerate(rows, start=2):
        mapped = {}
        for target_field, source_column in target_to_source.items():
            mapped[target_field] = normalize_text(row.get(source_column))

        if default_department_name:
            mapped["department_name"] = normalize_text(default_department_name)

        row_errors = []

        if not normalize_text(mapped.get("title")):
            row_errors.append("Missing required field: title")

        vendor_name = normalize_text(mapped.get("vendor_name"))
        vendor_code = normalize_text(mapped.get("vendor_code"))
        if vendor_name or vendor_code:
            existing_vendor = find_vendor_for_import(
                vendor_name=vendor_name,
                vendor_code=vendor_code,
            )
            if not existing_vendor and vendor_name:
                vendors_to_create += 1

        if row_errors:
            skipped_rows += 1
            errors.append(
                {
                    "row_number": index,
                    "source_identifier": mapped.get("title") or row.get(next(iter(row.keys()), ""), ""),
                    "error_message": "; ".join(row_errors),
                }
            )
        else:
            valid_rows += 1

        if len(preview_rows) < preview_limit:
            preview_rows.append(mapped)

    return {
        "total_rows": len(rows),
        "valid_rows": valid_rows,
        "skipped_rows": skipped_rows,
        "vendors_to_create": vendors_to_create,
        "preview_rows": preview_rows,
        "errors": errors,
    }

def normalize_import_header(value: str | None) -> str:
    value = normalize_text(value) or ""
    value = value.lower()
    value = value.replace("&", " and ")
    value = value.replace("-", "_")
    value = value.replace("/", "_")
    value = value.replace(" ", "_")

    while "__" in value:
        value = value.replace("__", "_")

    return value.strip("_")


def get_import_field_aliases(import_type: str) -> dict[str, list[str]]:
    import_type = (import_type or "").strip().lower()

    if import_type == "vendors":
        return {
            "vendor_name": ["vendor_name", "vendor", "name", "vendorname"],
            "vendor_code": ["vendor_code", "vendorcode", "code"],
            "website": ["website", "url", "site"],
            "main_phone": ["main_phone", "phone", "telephone"],
            "billing_email": ["billing_email", "billingemail"],
            "support_email": ["support_email", "supportemail"],
            "sales_contact_name": ["sales_contact_name", "salescontactname", "contact_name"],
            "sales_contact_email": ["sales_contact_email", "salescontactemail", "contact_email"],
            "notes": ["notes", "comments", "description"],
        }

    return {
        "title": ["title", "item_service_name", "item_name", "service_name", "name"],
        "record_type": ["record_type", "type"],
        "vendor_name": ["vendor_name", "vendor", "vendorname"],
        "vendor_code": ["vendor_code", "vendorcode"],
        "category_name": ["category_name", "category"],
        "account_code": ["account_code", "accountcode"],
        "po_number": ["po_number", "ponumber", "po"],
        "purchase_date": ["purchase_date", "purchasedate"],
        "service_start_date": ["service_start_date", "servicestartdate", "start_date", "startdate"],
        "term_length": ["term_length", "termlength"],
        "term_unit": ["term_unit", "termunit"],
        "expiration_date": ["expiration_date", "expirationdate", "end_date", "enddate"],
        "renewal_date": ["renewal_date", "renewaldate"],
        "notify_days_before": ["notify_days_before", "notifydaysbefore", "days_before"],
        "notification_recipients": ["notification_recipients", "notificationrecipients", "recipients"],
        "status": ["status"],
        "cost": ["cost", "amount", "price"],
        "notes": ["notes", "comments", "description"],
    }


def infer_import_field_map(source_headers: list[str], import_type: str) -> dict[str, str]:
    aliases = get_import_field_aliases(import_type)

    normalized_to_original = {}
    for header in source_headers:
        normalized_to_original[normalize_import_header(header)] = header

    inferred = {}

    for target_field, alias_list in aliases.items():
        for alias in alias_list:
            normalized_alias = normalize_import_header(alias)
            if normalized_alias in normalized_to_original:
                inferred[target_field] = normalized_to_original[normalized_alias]
                break

    return inferred