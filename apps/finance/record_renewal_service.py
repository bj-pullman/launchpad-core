"""Compose existing Renewal, Cycle and Record link operations."""
from .db import get_connection, finance_transaction
from .record_names import record_display_name
from . import renewal_service as renewals


def renewal_options(department, query=""):
    with get_connection() as conn:
        rows = conn.execute("""SELECT DISTINCT r.id AS renewal_id, r.renewal_name,
            r.department_name, c.id AS cycle_id, c.fiscal_year_label, c.expected_cost,
            COALESCE(v.friendly_name,v.vendor_name,'') AS vendor_name,
            cat.category_name
            FROM finance_renewals r
            LEFT JOIN finance_renewal_cycles c ON c.renewal_id=r.id
            LEFT JOIN finance_vendors v ON v.id=r.primary_vendor_id
            LEFT JOIN finance_categories cat ON cat.id=r.category_id
            WHERE r.department_name=? AND r.status NOT IN ('discontinued','replaced') AND (
                (r.renewal_name || char(10) || COALESCE(v.vendor_name,'') || char(10) ||
                 COALESCE(v.friendly_name,'') || char(10) || r.department_name || char(10) ||
                 COALESCE(cat.category_name,'') || char(10) || COALESCE(c.fiscal_year_label,'')) LIKE ?
                OR EXISTS (SELECT 1 FROM finance_renewal_record_links l
                    JOIN finance_renewal_cycles rc ON rc.id=l.renewal_cycle_id
                    JOIN finance_records fr ON fr.id=l.finance_record_id
                    WHERE rc.renewal_id=r.id AND fr.department_name=? AND
                    (fr.title || char(10) || COALESCE(fr.friendly_name,'') || char(10) || COALESCE(fr.po_number,'')) LIKE ?))
            ORDER BY r.renewal_name, c.fiscal_year_label DESC LIMIT 50""",
            (department, "%"+query.strip()+"%", department, "%"+query.strip()+"%")).fetchall()
    return [dict(row) for row in rows]


def renewal_from_record(record_id, department, user_id, *, mode, cycle_id=None, renewal_id=None, fiscal_year_id=None, replace=False):
    with finance_transaction() as conn:
        row = conn.execute("SELECT * FROM finance_records WHERE id=? AND department_name=? AND status NOT IN ('deleted','archived')",
                           (record_id, department)).fetchone()
        if not row:
            raise ValueError("Active Record not found.")
        record = dict(row)
        existing = renewals.get_record_renewal_link(record_id)
        if existing:
            if not replace:
                raise ValueError("This Record already has a Renewal. Use Change Link to update it.")
            renewals.unlink_record_from_renewal_cycle(
                renewal_cycle_id=existing["renewal_cycle_id"], finance_record_id=record_id,
                changed_by_user_id=user_id)
        year = None
        if fiscal_year_id:
            year = conn.execute("SELECT * FROM finance_fiscal_years WHERE id=? AND department_name=?",
                                (fiscal_year_id, department)).fetchone()
            if not year:
                raise ValueError("Choose a fiscal year in this department.")
        else:
            date = record.get("purchase_date") or record.get("service_start_date")
            if date:
                year = conn.execute("""SELECT * FROM finance_fiscal_years WHERE department_name=?
                    AND start_date<=? AND end_date>=? ORDER BY start_date DESC LIMIT 1""", (department,date,date)).fetchone()
            if not year:
                year = conn.execute("SELECT * FROM finance_fiscal_years WHERE department_name=? AND is_current=1 LIMIT 1",
                                    (department,)).fetchone()
        if mode == "create":
            if not year:
                raise ValueError("Configure or choose a fiscal year before creating a Renewal.")
            renewal_id, cycle_id = renewals.create_renewal(
                renewal_name=record_display_name(record), department_name=department,
                primary_vendor_id=record.get("vendor_id"), category_id=record.get("category_id"),
                purpose=f"Created from Record {record_id}" + (f"; PO {record['po_number']}" if record.get("po_number") else ""),
                notes=record.get("notes"), expected_renewal_hint=True,
                default_notification_days=record.get("notify_days_before") or 30,
                notification_recipients=record.get("notification_recipients"),
                fiscal_year_id=year["id"], expected_cost=record.get("cost"),
                renewal_date=record.get("renewal_date") or record.get("expiration_date"),
                service_start_date=record.get("service_start_date") or record.get("purchase_date"),
                service_end_date=record.get("expiration_date"), created_by_user_id=user_id)
        elif mode == "link":
            if cycle_id:
                cycle = renewals.get_renewal_cycle_by_id(cycle_id)
                renewal = renewals.get_renewal_by_id(cycle["renewal_id"]) if cycle else None
                if not renewal or renewal["department_name"] != department:
                    raise ValueError("Choose a Renewal cycle in this department.")
                renewal_id = renewal["id"]
            else:
                renewal = renewals.get_renewal_by_id(renewal_id)
                if not renewal or renewal["department_name"] != department or not year:
                    raise ValueError("Choose a Renewal and fiscal year in this department.")
                cycle_id = renewals.create_renewal_cycle(
                    renewal_id=renewal_id, fiscal_year_id=year["id"],
                    fiscal_year_label=renewals.get_fiscal_year_label(dict(year)),
                    expected_cost=record.get("cost"), created_by_user_id=user_id)
            if renewal["status"] in ("discontinued", "replaced"):
                raise ValueError("Choose an active Renewal.")
        else:
            raise ValueError("Choose Create Renewal or Link to Existing Renewal.")
        renewals.link_record_to_renewal_cycle(renewal_cycle_id=cycle_id,
            finance_record_id=record_id, linked_by_user_id=user_id)
        return renewal_id, cycle_id
