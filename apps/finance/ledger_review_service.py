"""Server-side Ledger review queries and immutable import-result snapshots."""

import json
import re
from contextlib import closing

from .db import get_connection
from .ledger_accounting_service import find_record_match
from .ledger_service import utc_now_iso
from .record_names import record_display_name


SNAPSHOT_MARKER = "\n[launchpad-ledger-review-v1]"
PAGE_SIZES = (10, 25, 50, 100)
REVIEW_STATUSES = ("unresolved", "linked", "ignored", "reviewed", "all")


def notes_with_snapshot(notes, snapshot):
    notes = (notes or "").split(SNAPSHOT_MARKER, 1)[0].rstrip()
    if snapshot is None:
        return notes
    return notes + SNAPSHOT_MARKER + json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":")
    )


def read_original_snapshot(run):
    """Never infer original review decisions from present-day statuses."""
    notes = run.get("run_notes") or ""
    if SNAPSHOT_MARKER in notes:
        try:
            snapshot = json.loads(notes.split(SNAPSHOT_MARKER, 1)[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("The saved Ledger import summary is invalid.") from exc
        if (not isinstance(snapshot, dict) or snapshot.get("version") != 1
                or not isinstance(snapshot.get("departments"), dict)):
            raise ValueError("The saved Ledger import summary is invalid.")
        return snapshot

    completed = (bool(run.get("completed_at"))
                 or str(run.get("status") or "").startswith("completed")
                 or notes.startswith("Ledger import completed."))
    if not completed:
        return None
    with closing(get_connection()) as conn:
        departments = [r[0] for r in conn.execute(
            "SELECT DISTINCT department_name FROM finance_ledger_transactions WHERE import_run_id=?",
            (run["id"],),
        ).fetchall()]
    single_department = len(departments) == 1
    linked_match = re.search(r"\bLinked to records:\s*(\d+)", notes)
    linked = int(linked_match.group(1)) if linked_match else None
    return {
        "version": 1, "legacy": True, "captured_at": run.get("completed_at"),
        "departments": {
            department: {
                "transactions": None,
                "inserted": int(run.get("created_rows") or 0) if single_department else None,
                "auto_linked": None, "linked": linked if single_department else None,
                "unresolved": None, "possible": None, "reviewed": None,
                "transaction_ids": None,
            } for department in departments
        },
    }


def capture_original_snapshot(conn, run_id, inserted_ids, automatic_ids, department_name=None):
    """Capture persisted unique transactions inside the import transaction."""
    rows = conn.execute(
        "SELECT * FROM finance_ledger_transactions WHERE import_run_id=? ORDER BY id",
        (run_id,),
    ).fetchall()
    groups = {department_name: []} if department_name else {}
    for row in rows:
        groups.setdefault(row["department_name"], []).append(dict(row))
    departments = {}
    for department, items in groups.items():
        result = dict(transactions=len(items), inserted=0, auto_linked=0, linked=0,
                      unresolved=0, possible=0, reviewed=0,
                      transaction_ids=[item["id"] for item in items])
        for item in items:
            result["inserted"] += int(item["id"] in inserted_ids)
            result["auto_linked"] += int(item["id"] in automatic_ids)
            if item["linked_record_id"]:
                result["linked"] += 1
            elif item["review_status"] in ("ignored", "reviewed"):
                result["reviewed"] += 1
            elif item["archive_status"] == "active":
                result["unresolved"] += 1
                result["possible"] += int(bool(find_record_match(conn, ledger=item)[1]))
        departments[department] = result
    return dict(version=1, legacy=False, captured_at=utc_now_iso(), departments=departments)


def get_import_context(department, run_id):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM finance_import_runs WHERE id=?", (run_id,)).fetchone()
        if not row or row["import_type"] != "transactions":
            raise ValueError("Ledger import not found.")
        run = dict(row)
        has_rows = conn.execute(
            "SELECT 1 FROM finance_ledger_transactions WHERE import_run_id=? AND department_name=? LIMIT 1",
            (run_id, department),
        ).fetchone() is not None
    snapshot = read_original_snapshot(run)
    original = snapshot.get("departments", {}).get(department) if snapshot else None
    if original is None and not has_rows:
        raise ValueError("Ledger import not found in this department.")
    return dict(run_id=run_id, original=original,
                legacy=bool(snapshot and snapshot.get("legacy")),
                exact_membership=bool(original is not None and original.get("transaction_ids") is not None))


def _scope_conditions(department, import_context=None):
    clauses = ["l.department_name=?", "l.archive_status='active'"]
    params = [department]
    if import_context:
        ids = (import_context.get("original") or {}).get("transaction_ids")
        if ids is not None:
            if not isinstance(ids, list) or any(type(value) is not int or value <= 0 for value in ids):
                raise ValueError("The saved import transaction list is invalid.")
            # Validated integer literals avoid SQLite's bound-parameter limit.
            clauses.append("l.id IN (" + ",".join(map(str, ids)) + ")" if ids else "0")
        else:
            clauses.append("l.import_run_id=?")
            params.append(import_context["run_id"])
    return clauses, params


def review_counts(department, import_context=None):
    clauses, params = _scope_conditions(department, import_context)
    with closing(get_connection()) as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS transactions,
                COALESCE(SUM(l.linked_record_id IS NOT NULL),0) AS linked,
                COALESCE(SUM(l.linked_record_id IS NULL AND l.review_status='ignored'),0) AS ignored,
                COALESCE(SUM(l.linked_record_id IS NULL AND l.review_status='reviewed'),0) AS reviewed,
                COALESCE(SUM(l.linked_record_id IS NULL AND l.review_status NOT IN ('ignored','reviewed')),0) AS unresolved
            FROM finance_ledger_transactions l WHERE """ + " AND ".join(clauses), params).fetchone()
    return {key: int(row[key]) for key in row.keys()}


def fiscal_year_options(department):
    with closing(get_connection()) as conn:
        return [row[0] for row in conn.execute("""
            SELECT DISTINCT fiscal_year_code FROM finance_ledger_transactions
            WHERE department_name=? AND archive_status='active'
                AND COALESCE(fiscal_year_code,'') != '' ORDER BY fiscal_year_code DESC
            """, (department,)).fetchall()]


def review_page(department, *, import_context=None, filters=None, page=1, per_page=25):
    filters = filters or {}
    per_page = per_page if per_page in PAGE_SIZES else 25
    page = max(1, int(page or 1))
    clauses, params = _scope_conditions(department, import_context)
    status = filters.get("review_status", "unresolved")
    if status not in REVIEW_STATUSES:
        status = "unresolved"
    if status == "unresolved":
        clauses.extend(["l.linked_record_id IS NULL", "l.review_status NOT IN ('ignored','reviewed')"])
    elif status == "linked":
        clauses.append("l.linked_record_id IS NOT NULL")
    elif status in ("ignored", "reviewed"):
        clauses.extend(["l.linked_record_id IS NULL", "l.review_status=?"])
        params.append(status)
    for key in ("fiscal_year_code", "transaction_code"):
        value = (filters.get(key) or "").strip()
        if value:
            clauses.append(f"l.{key}=?")
            params.append(value)
    search_columns = {
        "vendor_q": ("l.vendor_name", "l.vendor_code", "v.vendor_name", "v.friendly_name"),
        "account_q": ("l.fund", "l.budget_unit", "l.account_code"),
        "po_number": ("l.po_number", "l.normalized_po_number"),
        "q": ("l.title", "l.description", "l.vendor_name", "l.vendor_code", "v.vendor_name",
              "v.friendly_name", "l.po_number", "l.fund", "l.budget_unit", "l.account_code",
              "l.transaction_code", "l.transaction_code_label", "l.purchase_date", "r.title", "r.friendly_name"),
    }
    for key, columns in search_columns.items():
        value = (filters.get(key) or "").strip()
        if value:
            clauses.append("(" + " OR ".join(f"COALESCE({column},'') LIKE ?" for column in columns) + ")")
            params.extend([f"%{value}%"] * len(columns))
    joins = """ FROM finance_ledger_transactions l
        LEFT JOIN finance_vendors v ON v.id=l.vendor_id
        LEFT JOIN finance_records r ON r.id=l.linked_record_id """
    where = " WHERE " + " AND ".join(clauses)
    with closing(get_connection()) as conn:
        conn.execute("BEGIN")
        total = conn.execute("SELECT COUNT(*)" + joins + where, params).fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        offset = (page - 1) * per_page
        rows = conn.execute("""SELECT l.*, v.friendly_name AS vendor_friendly_name,
            v.vendor_name AS matched_vendor_name,
            COALESCE(NULLIF(TRIM(r.friendly_name),''),r.title) AS linked_record_title
            """ + joins + where + """ ORDER BY
            CASE WHEN COALESCE(l.purchase_date,'')='' THEN 1 ELSE 0 END,
            l.purchase_date DESC, l.id DESC LIMIT ? OFFSET ?""",
            [*params, per_page, offset]).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            actionable = item["linked_record_id"] is None and item["review_status"] not in ("ignored", "reviewed")
            item.update(actionable=actionable, suggested_record_id=None, suggested_name="", confidence=0, match_reason="")
            if actionable:
                record_id, confidence, reason = find_record_match(conn, ledger=item)
                record = conn.execute("SELECT * FROM finance_records WHERE id=?", (record_id,)).fetchone() if record_id else None
                item.update(suggested_record_id=record_id, suggested_name=record_display_name(record),
                            confidence=confidence, match_reason=reason or "No safe automatic match")
            result.append(item)
    return dict(rows=result, total=total, page=page, per_page=per_page, total_pages=total_pages,
                first=offset + 1 if total else 0, last=min(offset + per_page, total),
                has_previous=page > 1, has_next=page < total_pages)


def record_choices(department, query="", page=1, *, all_records=False):
    page = max(1, int(page or 1))
    page_size = 50
    term = "%" + query.strip() + "%"
    with closing(get_connection()) as conn:
        sql = """
            SELECT r.id, r.title, r.friendly_name, r.po_number,
                COALESCE(NULLIF(TRIM(v.friendly_name),''),v.vendor_name) AS vendor_name
            FROM finance_records r LEFT JOIN finance_vendors v ON v.id=r.vendor_id
            WHERE r.department_name=? AND r.status NOT IN ('deleted','archived') AND (
                COALESCE(r.friendly_name,'') LIKE ? OR COALESCE(r.title,'') LIKE ?
                OR COALESCE(r.po_number,'') LIKE ? OR COALESCE(v.vendor_name,'') LIKE ?
                OR COALESCE(v.friendly_name,'') LIKE ? OR CAST(r.id AS TEXT) LIKE ?)
            ORDER BY COALESCE(NULLIF(TRIM(r.friendly_name),''),r.title) COLLATE NOCASE, r.id"""
        params = [department, *([term] * 6)]
        if not all_records:
            sql += " LIMIT ? OFFSET ?"
            params.extend([page_size + 1, (page - 1) * page_size])
        rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows if all_records else rows[:page_size]:
        item = dict(row)
        display_name = record_display_name(item)
        parts = [display_name, f"Record #{item['id']}"]
        if item["title"] and item["title"] != display_name:
            parts.append(item["title"])
        if item["vendor_name"]:
            parts.append(item["vendor_name"])
        if item["po_number"]:
            parts.append(f"PO {item['po_number']}")
        result.append(dict(id=item["id"], label=" · ".join(parts)))
    return dict(rows=result, page=1 if all_records else page, has_more=not all_records and len(rows) > page_size)
