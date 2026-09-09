"""Record workflows built on the Ledger accounting and Renewal services."""
from .db import get_connection
from .ledger_accounting_service import (
    normalize_po, find_record_match, link_ledger_to_record, _po_totals,
)
from .ledger_record_service import update_record_financials_from_ledger, create_record_from_ledger
from .ledger_service import money, utc_now_iso
from .record_names import record_display_name


def records_for_po(conn, department, po, exclude_id=None):
    base = normalize_po(po)
    if not base:
        return []
    rows = conn.execute("""SELECT * FROM finance_records WHERE department_name=?
        AND status NOT IN ('deleted', 'archived')""", (department,)).fetchall()
    return [dict(row) for row in rows if row["id"] != exclude_id and normalize_po(row["po_number"]) == base]


def reconcile_record(conn, record_id, user_id=None):
    record = conn.execute("SELECT * FROM finance_records WHERE id=?", (record_id,)).fetchone()
    if not record or record["status"] in ("deleted", "archived"):
        return 0
    rows = conn.execute("""SELECT * FROM finance_ledger_transactions
        WHERE department_name=? AND linked_record_id IS NULL
        AND archive_status='active' AND review_status NOT IN ('ignored', 'reviewed')""",
        (record["department_name"],)).fetchall()
    count = 0
    for row in rows:
        match_id, confidence, reason = find_record_match(conn, ledger=dict(row))
        if match_id == record_id and confidence >= 90:
            link_ledger_to_record(conn, ledger_transaction_id=row["id"], record_id=record_id,
                                  confidence=confidence, reason=reason)
            count += 1
    if count:
        update_record_financials_from_ledger(conn, record_id=record_id, changed_by_user_id=user_id)
    return count


def po_preview(department, po, exclude_id=None):
    base = normalize_po(po)
    with get_connection() as conn:
        duplicates = records_for_po(conn, department, po, exclude_id)
        rows = conn.execute("""SELECT * FROM finance_ledger_transactions WHERE department_name=?
            AND archive_status != 'deleted'""", (department,)).fetchall() if base else []
        rows = [dict(row) for row in rows if normalize_po(row["po_number"]) == base]
    # Keep fiscal years separate so a reused PO never produces a misleading total.
    years = {}
    for row in rows:
        years.setdefault(row["fiscal_year_code"] or "Unassigned", []).append(row)
    totals = []
    for year, items in years.items():
        summary = _po_totals(items)
        totals.append({"fiscal_year": year, "transactions": len(items),
                       **{key: money(value) for key, value in summary.items()}})
    return {"po": base, "transactions": len(rows), "years": totals,
            "duplicates": [{"id": r["id"], "name": record_display_name(r)} for r in duplicates]}


def record_relationships(record_id):
    with get_connection() as conn:
        activity = conn.execute("""SELECT fiscal_year_code, COUNT(*) AS count
            FROM finance_ledger_transactions WHERE linked_record_id=? AND archive_status != 'deleted'
            GROUP BY fiscal_year_code""", (record_id,)).fetchall()
        orders = conn.execute("""SELECT DISTINCT p.* FROM finance_purchase_orders p
            JOIN finance_ledger_transactions l ON l.purchase_order_id=p.id
            WHERE l.linked_record_id=? AND l.archive_status != 'deleted'""", (record_id,)).fetchall()
    return {"activity": [dict(r) for r in activity], "orders": [dict(r) for r in orders]}


def record_options(department, query=""):
    term = "%" + query.strip() + "%"
    with get_connection() as conn:
        rows = conn.execute("""SELECT r.*, v.vendor_name FROM finance_records r
            LEFT JOIN finance_vendors v ON v.id=r.vendor_id WHERE r.department_name=?
            AND r.status NOT IN ('deleted','archived') AND
            (COALESCE(r.friendly_name,'') || char(10) || r.title || char(10) ||
             COALESCE(r.po_number,'') || char(10) || COALESCE(v.vendor_name,'')) LIKE ?
            ORDER BY COALESCE(NULLIF(TRIM(r.friendly_name),''), r.title) COLLATE NOCASE LIMIT 50""",
            (department, term)).fetchall()
    return [{**dict(r), "display_name": record_display_name(r)} for r in rows]


def review_rows(department, run_id=None, page=1):
    params = [department]
    where = "department_name=? AND linked_record_id IS NULL AND archive_status='active' AND review_status NOT IN ('ignored','reviewed')"
    if run_id:
        where += " AND import_run_id=?"
        params.append(run_id)
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM finance_ledger_transactions WHERE " + where, params).fetchone()[0]
        rows = conn.execute("SELECT * FROM finance_ledger_transactions WHERE " + where + " ORDER BY id DESC LIMIT 50 OFFSET ?",
                            [*params, (max(page, 1)-1)*50]).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            record_id, confidence, reason = find_record_match(conn, ledger=item)
            record = conn.execute("SELECT * FROM finance_records WHERE id=?", (record_id,)).fetchone() if record_id else None
            item.update(suggested_record_id=record_id, suggested_name=record_display_name(record),
                        confidence=confidence, match_reason=reason or "No safe automatic match")
            result.append(item)
    return {"rows": result, "total": count, "page": page, "has_next": page*50 < count}


def import_summary(department, run_id):
    with get_connection() as conn:
        rows = conn.execute("""SELECT * FROM finance_ledger_transactions
            WHERE department_name=? AND import_run_id=? AND archive_status != 'deleted'""",
            (department, run_id)).fetchall()
        result = {"transactions": len(rows), "linked": 0, "possible": 0, "needs_review": 0, "reviewed": 0}
        for row in rows:
            if row["linked_record_id"]:
                result["linked"] += 1
            elif row["review_status"] in ("ignored", "reviewed"):
                result["reviewed"] += 1
            elif find_record_match(conn, ledger=dict(row))[1]:
                result["possible"] += 1
            else:
                result["needs_review"] += 1
    return result


def review_action(department, ledger_id, action, user_id, record_id=None):
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM finance_ledger_transactions WHERE id=? AND department_name=?",
                           (ledger_id, department)).fetchone()
        if not row or row["archive_status"] != "active":
            raise ValueError("Ledger transaction not found.")
        if row["linked_record_id"]:
            raise ValueError("This transaction is already linked. Reload to see its Record.")
        if action in ("ignore", "reviewed"):
            conn.execute("UPDATE finance_ledger_transactions SET review_status=?, updated_at=? WHERE id=?",
                         ("ignored" if action == "ignore" else "reviewed", utc_now_iso(), ledger_id))
            return None
        if action == "create":
            if records_for_po(conn, department, row["po_number"]):
                raise ValueError("An active Record already uses this PO. Choose a Record before creating another.")
            record_id = create_record_from_ledger(conn, ledger=dict(row), created_by_user_id=user_id)
        elif action != "link":
            raise ValueError("Invalid review action.")
        record = conn.execute("SELECT * FROM finance_records WHERE id=? AND department_name=? AND status NOT IN ('deleted','archived')",
                              (record_id, department)).fetchone()
        if not record:
            raise ValueError("Choose an active Record in this department.")
        link_ledger_to_record(conn, ledger_transaction_id=ledger_id, record_id=record_id,
                              confidence=100, reason="Manually selected during Ledger review")
        conn.execute("""UPDATE finance_record_ledger_links SET link_type='manual'
            WHERE ledger_transaction_id=? AND finance_record_id=?""", (ledger_id, record_id))
        update_record_financials_from_ledger(conn, record_id=record_id, changed_by_user_id=user_id)
        if action == "create":
            reconcile_record(conn, record_id, user_id)
        conn.execute("""INSERT INTO finance_record_history
            (finance_record_id, event_type, summary, changed_by_user_id, changed_at)
            VALUES (?, 'ledger_linked', ?, ?, ?)""",
            (record_id, f"Ledger transaction {ledger_id} linked from review.", user_id, utc_now_iso()))
        return record_id
