from __future__ import annotations

import sys
import tempfile
import types
import unittest
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Flask, session
warnings.filterwarnings("ignore", category=ResourceWarning)

# Match the existing tests: importing the app factory would start scheduled jobs.
ROOT = Path(__file__).resolve().parents[1]
if "modules.core" not in sys.modules:
    package = types.ModuleType("modules.core")
    package.__path__ = [str(ROOT / "modules/core")]
    sys.modules["modules.core"] = package

from modules.core.auth import session_policy as policy
from modules.core.settings import settings_db
from modules.core.settings.settings_service import set_setting
from modules.core.identity import identity_db, user_service
from modules.core.identity import rbac_db
from apps.finance import db, service, ledger_service, ledger_accounting_service as accounting
from apps.finance import ledger_import_service as importer
from apps.finance.ledger_vendor_service import get_or_create_vendor_for_ledger_import
from apps.finance.record_names import record_display_name
from apps.finance import record_workflow_service as workflow, record_renewal_service as renewal_workflow
from apps.finance import renewal_service


class IsolatedDatabases(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for module, attrs in [(db, {"DATA_DIR": root, "DB_PATH": root/"finance.db"}),
                              (settings_db, {"DATA_DIR": root, "SETTINGS_DB_PATH": root/"settings.db"}),
                              (identity_db, {"DATA_DIR": root, "IDENTITY_DB_PATH": root/"identity.db"}),
                              (rbac_db, {"DATA_DIR":root, "RBAC_DB_PATH":root/"rbac.db"})]:
            for name, value in attrs.items():
                stub = patch.object(module, name, value)
                stub.start(); self.addCleanup(stub.stop)
        settings_db.init_settings_db()
        identity_db.init_identity_db()
        rbac_db.init_rbac_db()
        db.init_finance_db()
        ledger_service.ensure_finance_ledger_schema()

    def record(self, **kwargs):
        values = dict(record_type="software_license", title="IMPORTED ADOBE SYSTEMS", department_name="Technology", po_number="12345")
        values.update(kwargs)
        return service.create_record(**values)

    def ledger(self, **kwargs):
        values = dict(department_name="Technology", fiscal_year_code="FY27", source_hash="test"+str(kwargs),
                      transaction_code="20", ledger_kind="expenditure", title="Imported activity", vendor_name="Adobe",
                      po_number="12345-01", normalized_po_number="12345", expenditure_amount="100.00",
                      encumbrance_amount="0.00", purchase_date="2026-08-01")
        values.update(kwargs)
        with db.get_connection() as conn:
            return importer.insert_ledger_transaction(conn, ledger=values)[0]


class SessionTests(IsolatedDatabases):
    def setUp(self):
        super().setUp()
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret-only"
        self.app.config["TESTING"] = True
        self.app.add_url_rule("/login", "auth.login", lambda: "login")
        policy.register_session_policy(self.app)
        self.app.add_url_rule("/page", "page", lambda: "ok")
        self.client = self.app.test_client()

    def login(self, **values):
        now = datetime.now(timezone.utc)
        with self.client.session_transaction() as data:
            data.update(is_authenticated=True, user_id=1, authenticated_at=now.isoformat(),
                        last_activity=(now-timedelta(minutes=2)).isoformat(), csrf_token="test-csrf")
            data.update(values)

    def test_normal_activity_and_background(self):
        self.login()
        with self.client.session_transaction() as data:
            old = data["last_activity"]
        self.client.get("/page", headers={"X-Launchpad-Background": "1"})
        with self.client.session_transaction() as data:
            self.assertEqual(data["last_activity"], old)
        self.client.get("/page")
        with self.client.session_transaction() as data:
            self.assertGreater(data["last_activity"], old)

    def test_idle_and_absolute_expiry_logs_no_sensitive_data(self):
        for field, delta, reason in [("last_activity", timedelta(minutes=31), "idle_timeout"),
                                     ("authenticated_at", timedelta(hours=9), "absolute_timeout")]:
            with self.subTest(reason=reason):
                self.login(**{field: (datetime.now(timezone.utc)-delta).isoformat()}, user_email="private@example.test")
                with self.assertLogs(self.app.logger, level="INFO") as logs:
                    response = self.client.get("/page", headers={"X-Requested-With":"XMLHttpRequest"})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json["reason"], reason)
                self.assertIn(reason, " ".join(logs.output))
                self.assertNotIn("private@example.test", " ".join(logs.output))
                self.assertNotIn("test-csrf", " ".join(logs.output))

    def test_never_and_live_policy_changes(self):
        set_setting("security.session_idle_timeout_minutes", "0")
        set_setting("security.session_absolute_timeout_hours", "0")
        old = (datetime.now(timezone.utc)-timedelta(days=100)).isoformat()
        self.login(authenticated_at=old, last_activity=old)
        self.assertEqual(self.client.get("/page").status_code, 200)
        set_setting("security.session_absolute_timeout_hours", "1")
        self.assertEqual(self.client.get("/page").status_code, 302)

    def test_malformed_missing_naive_and_future_timestamps(self):
        for field in ("authenticated_at", "last_activity"):
            for value in (None, "bad", 123, (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()):
                self.login(**{field: value})
                response = self.client.get("/page", headers={"X-Requested-With":"XMLHttpRequest"})
                self.assertEqual(response.json["reason"], "invalid_"+field)
        self.login(authenticated_at=datetime.now().isoformat())
        # Explicitly use UTC-naive for the legacy UTC representation.
        self.login(authenticated_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat())
        self.assertEqual(self.client.get("/page").status_code, 200)

    def test_keepalive_requires_authentication_and_csrf(self):
        self.assertEqual(self.client.post("/auth/session/activity").status_code, 401)
        set_setting("security.session_keep_active", "true")
        self.login()
        self.assertEqual(self.client.post("/auth/session/activity").status_code, 400)
        self.assertEqual(self.client.post("/auth/session/activity", headers={"X-CSRF-Token":"test-csrf"}).status_code, 204)

    def test_remember_lifetime_is_per_session(self):
        set_setting("security.session_absolute_timeout_hours", "0")
        set_setting("security.session_remember_me_days", "7")
        original = self.app.permanent_session_lifetime
        self.login(remember_me=True, _permanent=True)
        cookie = self.client.get("/page").headers["Set-Cookie"]
        self.assertIn("Expires=", cookie)
        other = self.app.test_client()
        with other.session_transaction() as data:
            data.update(is_authenticated=True, user_id=2, authenticated_at=datetime.now(timezone.utc).isoformat(), last_activity=datetime.now(timezone.utc).isoformat())
        self.assertNotIn("Expires=", other.get("/page").headers["Set-Cookie"])
        self.assertEqual(self.app.permanent_session_lifetime, original)

    def test_remember_does_not_bypass_absolute_limit(self):
        set_setting("security.session_remember_me_days", "30")
        self.login(remember_me=True, _permanent=True,
                   authenticated_at=(datetime.now(timezone.utc)-timedelta(hours=9)).isoformat())
        response=self.client.get("/page",headers={"Accept":"application/json"})
        self.assertEqual(response.json["reason"],"absolute_timeout")

    def test_invalid_identity_and_cookie_are_logged(self):
        self.login(user_id=None)
        response=self.client.get("/page",headers={"Accept":"application/json"})
        self.assertEqual(response.json["reason"],"authentication_state_invalid")
        self.client.set_cookie("session","sensitive-invalid-cookie")
        with self.assertLogs(self.app.logger,level="INFO") as logs:
            self.client.get("/page")
        self.assertIn("invalid_cookie_signature"," ".join(logs.output))
        self.assertNotIn("sensitive-invalid-cookie"," ".join(logs.output))

    def test_global_flask_cookie_age_does_not_override_never(self):
        from itsdangerous import TimestampSigner
        import time
        set_setting("security.session_absolute_timeout_hours","0")
        self.app.permanent_session_lifetime=timedelta(seconds=1)
        self.login()
        with self.client.session_transaction() as data:
            payload=dict(data)
        with patch.object(TimestampSigner,"get_timestamp",return_value=int(time.time())-60):
            cookie=self.app.session_interface.get_signing_serializer(self.app).dumps(payload)
        self.client.set_cookie("session",cookie)
        self.client.get("/page")
        with self.client.session_transaction() as data:
            self.assertTrue(data["is_authenticated"])

    def test_cookie_security_changes_apply_without_restart(self):
        self.login()
        set_setting("security.cookie_secure","true")
        set_setting("security.cookie_samesite","Strict")
        response=self.client.get("/page",base_url="https://localhost")
        self.assertIn("Secure",response.headers["Set-Cookie"])
        self.assertIn("HttpOnly",response.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict",response.headers["Set-Cookie"])


class FinanceWorkflowTests(IsolatedDatabases):
    def import_rows(self, rows, run_id=1):
        with patch.object(importer,"get_import_run_by_id",return_value={"stored_filename":"fixture.csv"}), \
             patch.object(importer,"read_import_rows",return_value=rows), \
             patch.object(importer,"_mapped_row",side_effect=lambda row,*args:row), \
             patch.object(importer,"update_import_run_results"), \
             patch.object(importer,"log_import_run_error") as errors:
            result=importer.execute_ledger_import(run_id=run_id,default_department_name="Technology",created_by_user_id=1)
        self.assertEqual(result["error_rows"],0,errors.call_args_list)
        return result

    def test_ledger_import_pipeline_preserves_curated_records_and_vendors(self):
        self.make_year()
        vendor=service.create_vendor(vendor_name="ADOBE",vendor_code="A1",friendly_name="Adobe",notes="Vendor notes")
        record_id=self.record(vendor_id=vendor,friendly_name="Creative Cloud",notes="Record notes",category_id=17)
        for year, day in [(26,"2025-08-01"),(27,"2026-08-01")]:
            self.import_rows([dict(transaction_code="20",vendor_name="NEW IMPORT NAME",vendor_code="A1",
                po_number="12345-01",purchase_date=day,description="Accounting description",expenditure_amount="200.00")],run_id=year)
        record=service.get_record_by_id(record_id)
        self.assertEqual(record["friendly_name"],"Creative Cloud")
        self.assertEqual(record["title"],"IMPORTED ADOBE SYSTEMS")
        self.assertEqual(record["notes"],"Record notes")
        self.assertEqual(record["category_id"],17)
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_vendors").fetchone()[0],1)
            vendor_row=conn.execute("SELECT * FROM finance_vendors WHERE id=?",(vendor,)).fetchone()
            self.assertEqual(vendor_row["friendly_name"],"Adobe")
            self.assertEqual(vendor_row["notes"],"Vendor notes")

    def test_import_reuses_manual_links_and_review_decisions(self):
        rows=[dict(transaction_code="20",vendor_name="ADOBE",po_number="12345",purchase_date="2026-08-01",
                   description="Accounting description",expenditure_amount="200.00")]
        self.import_rows(rows)
        with db.get_connection() as conn:
            ledger_id=conn.execute("SELECT id FROM finance_ledger_transactions").fetchone()[0]
        workflow.review_action("Technology",ledger_id,"reviewed",1)
        self.import_rows(rows)
        self.assertEqual(workflow.review_rows("Technology")["total"],0)
        manual=self.record(title="Manually chosen",po_number="OTHER")
        workflow.review_action("Technology",ledger_id,"link",1,manual)
        self.record(title="PO alternative")
        self.import_rows(rows)
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT linked_record_id FROM finance_ledger_transactions WHERE id=?",(ledger_id,)).fetchone()[0],manual)

    def test_ambiguous_import_does_not_create_third_record(self):
        self.record();self.record(title="Duplicate")
        self.import_rows([dict(transaction_code="17",vendor_name="ADOBE",po_number="12345-01",
                              purchase_date="2026-08-01",encumbrance_amount="300.00")])
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_records").fetchone()[0],2)
        summary=workflow.import_summary("Technology",1)
        self.assertEqual(summary["possible"],1)
        self.assertEqual(summary["linked"],0)

    def test_legacy_record_import_preserves_metadata(self):
        record_id=self.record(friendly_name="Curated",category_id=11,notes="User notes",cost="100")
        service.upsert_record_from_import(mapped={"department_name":"Technology","po_number":"12345-01",
            "friendly_name":"Import name","notes":"Import notes","cost":"20"},vendor_id=None,category_id=22,
            title="NEW SOURCE TITLE",term_length=None,notify_days_before=30)
        record=service.get_record_by_id(record_id)
        self.assertEqual((record["friendly_name"],record["category_id"],record["notes"],record["title"]),
                         ("Curated",11,"User notes","IMPORTED ADOBE SYSTEMS"))
        self.assertEqual(record["cost"],"120.00")
    def test_vendor_reused_across_years_and_metadata_preserved(self):
        with db.get_connection() as conn:
            vendor_id, created = get_or_create_vendor_for_ledger_import(conn, vendor_name="ADOBE SYSTEMS", vendor_code="A1")
            self.assertTrue(created)
            conn.execute("""UPDATE finance_vendors SET friendly_name='Adobe', website='https://example.test',
                main_phone='123', billing_email='billing@example.test', support_email='support@example.test',
                sales_contact_name='Contact', sales_contact_email='sales@example.test', notes='Curated' WHERE id=?""", (vendor_id,))
            before = dict(conn.execute("SELECT * FROM finance_vendors WHERE id=?",(vendor_id,)).fetchone())
            for year in ("FY26", "FY27"):
                actual, created = get_or_create_vendor_for_ledger_import(conn, vendor_name="CHANGED SOURCE", vendor_code="A1")
                self.assertEqual(actual, vendor_id); self.assertFalse(created)
                self.assertEqual(dict(conn.execute("SELECT * FROM finance_vendors WHERE id=?",(vendor_id,)).fetchone()), before)
        for year in ("FY26", "FY27"):
            self.ledger(vendor_id=vendor_id, fiscal_year_code=year)
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_vendors").fetchone()[0], 1)

    def test_record_friendly_name_fallback_and_both_searches(self):
        record_id = self.record(friendly_name="Creative Cloud")
        self.assertEqual(record_display_name(service.get_record_by_id(record_id)), "Creative Cloud")
        self.assertEqual(record_display_name({"title":"Source", "friendly_name":"  "}), "Source")
        for query in ("Creative", "ADOBE SYSTEMS"):
            self.assertEqual(service.list_records_for_department_page(department_name="Technology", status="active", q=query)["total"],1)
            self.assertEqual(workflow.record_options("Technology", query)[0]["id"], record_id)

    def test_record_created_after_ledger_links_and_preserves_name(self):
        ledger_id = self.ledger()
        record_id = self.record(friendly_name="Creative Cloud", notes="Curated")
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT linked_record_id FROM finance_ledger_transactions WHERE id=?",(ledger_id,)).fetchone()[0], record_id)
        record = service.get_record_by_id(record_id)
        self.assertEqual(record["title"], "IMPORTED ADOBE SYSTEMS")
        self.assertEqual(record["friendly_name"], "Creative Cloud")
        self.assertEqual(record["notes"], "Curated")
        self.assertEqual(record["cost"], "100.00")

    def test_ambiguous_po_never_autolinks(self):
        one = self.record(po_number="12345-01")
        self.record(po_number="12345-02")
        ledger_id = self.ledger()
        with db.get_connection() as conn:
            ledger = dict(conn.execute("SELECT * FROM finance_ledger_transactions WHERE id=?",(ledger_id,)).fetchone())
            self.assertEqual(accounting.find_record_match(conn, ledger=ledger)[0], None)
            self.assertEqual(workflow.reconcile_record(conn, one), 0)
        self.assertEqual(len(workflow.po_preview("Technology", "12345")["duplicates"]),2)
        self.assertEqual(workflow.po_preview("Other", "12345")["transactions"],0)

    def test_record_edit_reconciles_and_ignores_review_decisions(self):
        record_id = self.record(po_number="OTHER", friendly_name="Curated")
        ledger_id = self.ledger()
        ignored = self.ledger(source_hash="ignored")
        workflow.review_action("Technology", ignored, "ignore", 1)
        service.update_record(record_id=record_id, record_type="renewal", title="IMPORTED", department_name="Technology", po_number="12345-02")
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT linked_record_id FROM finance_ledger_transactions WHERE id=?",(ledger_id,)).fetchone()[0],record_id)
            self.assertIsNone(conn.execute("SELECT linked_record_id FROM finance_ledger_transactions WHERE id=?",(ignored,)).fetchone()[0])
        self.assertEqual(service.get_record_by_id(record_id)["friendly_name"],"Curated")

    def test_manual_review_permissions_and_actions(self):
        ledger_id = self.ledger()
        other = self.record(department_name="Other")
        with self.assertRaises(ValueError):
            workflow.review_action("Technology", ledger_id, "link", 1, other)
        record_id = workflow.review_action("Technology", ledger_id, "create", 1)
        self.assertTrue(record_id)
        self.assertEqual(workflow.review_rows("Technology")["total"],0)

    def test_migration_preserves_existing_records(self):
        record_id = self.record()
        with db.get_connection() as conn:
            conn.execute("ALTER TABLE finance_records DROP COLUMN friendly_name")
        db.init_finance_db(); db.init_finance_db()
        record = service.get_record_by_id(record_id)
        self.assertIsNone(record["friendly_name"])
        self.assertEqual(record["title"],"IMPORTED ADOBE SYSTEMS")

    def make_year(self):
        with db.get_connection() as conn:
            conn.execute("""INSERT INTO finance_fiscal_years
                (department_name, code, short_code, year_number, friendly_name, start_date, end_date, status, is_current, created_at, updated_at)
                VALUES ('Technology','FY27','FY27',2027,'FY27','2026-07-01','2027-06-30','active',1,'now','now')""")

    def test_renewal_creation_search_and_link(self):
        self.make_year()
        record_id = self.record(friendly_name="Creative Cloud", purchase_date="2026-08-01", cost="18500")
        renewal_id, cycle_id = renewal_workflow.renewal_from_record(record_id,"Technology",1,mode="create")
        renewal = renewal_service.get_renewal_by_id(renewal_id)
        self.assertEqual(renewal["renewal_name"], "Creative Cloud")
        self.assertEqual(renewal_service.get_record_renewal_link(record_id)["renewal_cycle_id"],cycle_id)
        self.assertEqual(renewal_workflow.renewal_options("Technology","ADOBE")[0]["renewal_id"],renewal_id)
        self.assertEqual(renewal_workflow.renewal_options("Other","Creative"),[])
        second = self.record(title="Second", po_number="NEW")
        renewal_workflow.renewal_from_record(second,"Technology",1,mode="link",cycle_id=cycle_id)
        self.assertEqual(renewal_service.get_record_renewal_link(second)["renewal_cycle_id"],cycle_id)

    def test_renewal_failure_rolls_back_entity_and_cycle(self):
        self.make_year()
        record_id = self.record()
        with patch.object(renewal_service,"link_record_to_renewal_cycle",side_effect=ValueError("link failed")):
            with self.assertRaises(ValueError):
                renewal_workflow.renewal_from_record(record_id,"Technology",1,mode="create")
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_renewals").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_renewal_cycles").fetchone()[0],0)


class ThemeTests(IsolatedDatabases):
    def test_all_preferences_persist_and_migrate(self):
        user = user_service.create_user({"email":"theme@example.test","display_name":"Theme"})
        for value in ("light","dark","system"):
            user_service.update_user_theme_preference(user["id"],value)
            identity_db.init_identity_db()
            self.assertEqual(user_service.get_user_by_id(user["id"])["theme_preference"],value)
        self.assertEqual(user_service.normalize_theme_preference("invalid"),"light")


class RouteTests(IsolatedDatabases):
    def setUp(self):
        super().setUp()
        from apps.finance.blueprint import bp
        from apps.launchpad_ui import launchpad_ui_bp
        from apps.finance import access_service
        self.app = Flask(__name__, template_folder=str(ROOT/"templates"), static_folder=str(ROOT/"static"))
        self.app.secret_key = "isolated-route-test"
        self.app.config["TESTING"] = True
        self.app.add_url_rule("/login", "auth.login", lambda:"login")
        self.app.add_url_rule("/logout", "auth.logout", lambda:"logout")
        self.app.register_blueprint(launchpad_ui_bp)
        self.app.register_blueprint(bp)
        policy.register_session_policy(self.app)
        self.app.add_template_filter(lambda value: value or "", "localtime")
        self.app.add_template_filter(lambda value: value or "", "localdate")
        @self.app.context_processor
        def context():
            return dict(general_settings={}, current_user_theme=session.get("theme_preference","light"))
        stub=patch.object(access_service,"get_finance_permission_keys",return_value={"finance.admin","finance.budget.admin"})
        stub.start(); self.addCleanup(stub.stop)
        service.ensure_finance_department("Technology")
        service.set_department_finance_enabled("Technology", True)
        from apps.finance.budget_definition_schema_service import ensure_budget_definition_schema
        ensure_budget_definition_schema()
        FinanceWorkflowTests.make_year(self)
        with db.get_connection() as conn:
            conn.execute("UPDATE finance_fiscal_years SET adopted_budget='100000' WHERE department_name='Technology'")
        self.user = user_service.create_user({"email":"routes@example.test","display_name":"Routes"})
        self.client=self.app.test_client()
        with self.client.session_transaction() as data:
            now=datetime.now(timezone.utc).isoformat()
            data.update(is_authenticated=True,user_id=self.user["id"],authenticated_at=now,last_activity=now,
                csrf_token="test-csrf",user_permissions=["launchpad.settings.security.view","launchpad.settings.security.manage"])

    def test_changed_pages_render(self):
        record_id=self.record(friendly_name="Creative Cloud")
        self.ledger(po_number="UNLINKED")
        for path in ("/settings/security", "/finance/Technology/records", "/finance/Technology/records/new",
                     f"/finance/records/{record_id}", f"/finance/records/{record_id}/edit",
                     "/finance/Technology/ledger/review", "/finance/Technology/ledger"):
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertEqual(response.status_code,200, response.headers.get("Location"))
                self.assertIn(b"launchpad-shell.js",response.data)

    def test_inline_record_name_only_updates_name_and_history(self):
        record_id = self.record(friendly_name="Old", notes="Keep notes", cost="25")
        before = service.get_record_by_id(record_id)
        path = f"/finance/records/{record_id}/friendly-name"
        response = self.client.post(path, data={"csrf_token":"test-csrf", "friendly_name":"  New name  ", "title":"Ignore"})
        self.assertEqual(response.status_code, 302)
        after = service.get_record_by_id(record_id)
        self.assertEqual(after["friendly_name"], "New name")
        for key in before.keys() - {"friendly_name", "updated_at"}:
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(service.list_history_for_record(record_id)[0]["summary"], "Friendly Record Name updated.")
        self.client.post(path, data={"csrf_token":"test-csrf", "friendly_name":" "})
        self.assertEqual(record_display_name(service.get_record_by_id(record_id)), before["title"])

    def test_inline_name_permission_csrf_and_deleted_record(self):
        from apps.finance import record_workflow_routes
        record_id = self.record(friendly_name="Keep")
        path = f"/finance/records/{record_id}/friendly-name"
        self.assertEqual(self.client.post(path, data={"friendly_name":"Denied"}).status_code, 400)
        with patch.object(record_workflow_routes, "can_manage_department", return_value=False):
            self.assertEqual(self.client.post(path, data={"csrf_token":"test-csrf", "friendly_name":"Denied"}).status_code, 403)
        with patch.object(record_workflow_routes, "can_access_department", return_value=False):
            self.assertEqual(self.client.post(path, data={"csrf_token":"test-csrf"}).status_code, 403)
        with db.get_connection() as conn:
            conn.execute("UPDATE finance_records SET status='deleted' WHERE id=?", (record_id,))
        self.assertEqual(self.client.post(path, data={"csrf_token":"test-csrf"}).status_code, 409)
        self.assertEqual(service.get_record_by_id(record_id)["friendly_name"], "Keep")

    def test_record_detail_names_relationships_and_edit_navigation(self):
        from apps.finance import record_workflow_service
        record_id = self.record(friendly_name="Creative Cloud")
        relationships = {"activity":[{"count":3, "fiscal_year_code":None}],
                         "orders":[{"id":1, "normalized_po_number":"250045", "fiscal_year_code":None}]}
        with patch.object(record_workflow_service, "record_relationships", return_value=relationships):
            html = self.client.get(f"/finance/records/{record_id}").get_data(as_text=True)
        for text in ("<th>Friendly Record Name</th>", "<th>Imported/System Title</th>", "Creative Cloud", "IMPORTED ADOBE SYSTEMS", "Not linked", "Link Existing Renewal", "PO 250045"):
            self.assertIn(text, html)
        self.assertNotIn("Unassigned year", html)
        self.assertNotIn(" · None", html)
        self.assertNotIn("Save Renewal Link", html)
        html = self.client.get(f"/finance/records/{record_id}/edit").get_data(as_text=True)
        self.assertIn(f'href="/finance/records/{record_id}" class="finance-back-link"', html)
        self.assertIn("Exit without Saving", html)
        self.assertIn("Continue Editing", html)
        self.assertIn("Friendly Record Name (optional)", html)

    def test_full_edit_updates_friendly_record_name(self):
        from apps.finance import routes
        record_id = self.record(friendly_name="Old")
        with patch.object(routes, "maybe_send_renewal_notification_for_record", return_value=(False,"")):
            response = self.client.post(f"/finance/records/{record_id}/edit", data={"title":"SOURCE", "friendly_name":"Edited",
                "record_type":"software_license", "status":"active", "csrf_token":"test-csrf"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(service.get_record_by_id(record_id)["friendly_name"], "Edited")

    def test_detail_renewal_create_change_rollback_and_unlink(self):
        record_id = self.record(friendly_name="Creative Cloud")
        path = f"/finance/Technology/records/{record_id}/renewal"
        data = {"csrf_token":"test-csrf", "is_renewal":"on", "renewal_mode":"create"}
        self.assertEqual(self.client.post(path, data=data).status_code, 302)
        original = renewal_service.get_record_renewal_link(record_id)
        html = self.client.get(f"/finance/records/{record_id}").get_data(as_text=True)
        for text in ("finance-renewal-compact", "Creative Cloud", "View Renewal", "Change Link", "Unlink", original["fiscal_year_label"]):
            self.assertIn(text, html)
        self.client.post(path, data={**data, "renewal_mode":"link", "renewal_cycle_id":999999, "replace_link":"1"})
        self.assertEqual(renewal_service.get_record_renewal_link(record_id)["renewal_cycle_id"], original["renewal_cycle_id"])
        other = self.record(title="Other")
        _, cycle = renewal_workflow.renewal_from_record(other, "Technology", self.user["id"], mode="create")
        self.client.post(path, data={**data, "renewal_mode":"link", "renewal_cycle_id":cycle, "replace_link":"1"})
        self.assertEqual(renewal_service.get_record_renewal_link(record_id)["renewal_cycle_id"], cycle)
        unlink = f"/finance/records/{record_id}/renewal/unlink"
        self.assertEqual(self.client.post(unlink, data={"csrf_token":"test-csrf"}).status_code, 302)
        self.assertIsNone(renewal_service.get_record_renewal_link(record_id))
        self.assertIn(b"Not linked", self.client.get(f"/finance/records/{record_id}").data)

    def test_security_save_permissions_and_validation(self):
        response=self.client.post("/settings/security",data={"csrf_token":"test-csrf","session_idle_timeout_minutes":"0",
            "session_absolute_timeout_hours":"0","session_remember_me_days":"7","session_keep_active":"on",
            "require_login_for_launchpad":"on","cookie_secure":"on","cookie_httponly":"on","cookie_samesite":"Strict"})
        self.assertEqual(response.status_code,302)
        with self.app.test_request_context():
            saved=policy.read_policy()
            self.assertEqual(saved["session_idle_timeout_minutes"],0)
            self.assertTrue(saved["session_keep_active"])
            self.assertTrue(saved["require_login_for_launchpad"])
            self.assertTrue(saved["cookie_secure"])
            self.assertTrue(saved["cookie_httponly"])
            self.assertEqual(saved["cookie_samesite"],"Strict")
        invalid=self.client.post("/settings/security",data={"csrf_token":"test-csrf","session_idle_timeout_minutes":"0",
            "session_absolute_timeout_hours":"0","session_remember_me_days":"7","cookie_samesite":"None"})
        self.assertEqual(invalid.status_code,302)
        with self.app.test_request_context():
            self.assertEqual(policy.read_policy()["cookie_samesite"],"Strict")
        with self.client.session_transaction() as data:
            data["user_permissions"]=["launchpad.settings.security.view"]
        response=self.client.post("/settings/security",data={"csrf_token":"test-csrf"},headers={"Accept":"application/json"})
        self.assertEqual(response.status_code,403)

    def test_lookup_permission_boundary(self):
        self.record(friendly_name="Creative Cloud")
        self.assertEqual(self.client.get("/finance/Technology/records/search?q=Creative").status_code,200)
        from apps.finance import record_workflow_routes
        from apps.finance import setup_guard_routes
        with patch.object(record_workflow_routes,"can_access_department",return_value=False), patch.object(setup_guard_routes,"can_access_department",return_value=False):
            for path in ("/finance/Other/records/search", "/finance/Other/records/po-preview", "/finance/Other/renewals/search", "/finance/Other/ledger/review"):
                self.assertEqual(self.client.get(path).status_code,403)

    def test_templates_compile(self):
        for name in self.app.jinja_env.list_templates():
            self.app.jinja_env.get_template(name)

    def test_shared_account_and_theme_shell_render_across_apps(self):
        account_source = (ROOT/"templates/layouts/_account_dropdown.html").read_text(encoding="utf-8")
        for base in (ROOT/"apps/launchpad_ui/templates/launchpad_ui/base.html",
                     ROOT/"apps/snipeops/templates/snipeops/base.html"):
            self.assertIn('layouts/_account_dropdown.html', base.read_text(encoding="utf-8"))
        self.assertIn('nav-dropdown-menu-account', account_source)
        self.assertIn('layouts/_theme_picker.html', account_source)
        for path in ("/settings/security", "/finance/Technology/records"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn('class="nav-dropdown nav-dropdown-account"', html)
            self.assertIn('data-theme-choice="system"', html)
            self.assertIn('data-theme-choice="light"', html)
            self.assertIn('data-theme-choice="dark"', html)
            self.assertIn('dataset.themePreference', html)
        user_service.update_user_theme_preference(self.user["id"], "dark")
        with self.client.session_transaction() as data:
            data["theme_preference"] = "dark"
        html = self.client.get("/settings/security").get_data(as_text=True)
        self.assertIn('data-theme-choice="dark" aria-pressed="true"', html)
        user_service.update_user_theme_preference(self.user["id"], "light")
        with self.client.session_transaction() as data:
            data["theme_preference"] = "light"

    def test_shared_applications_dropdown_keeps_permission_driven_links_and_polished_styles(self):
        for base in (ROOT/"apps/launchpad_ui/templates/launchpad_ui/base.html",
                     ROOT/"apps/snipeops/templates/snipeops/base.html"):
            source=base.read_text(encoding="utf-8")
            self.assertIn("nav-dropdown-menu-applications",source)
            self.assertIn("{% if launchpad_apps %}",source)
            self.assertIn("{% for app in launchpad_apps %}",source)
            self.assertIn("url_for(app.endpoint)",source)
        shared_css=(ROOT/"static/launchpad-theme.css").read_text(encoding="utf-8")
        self.assertIn(".nav-dropdown-menu-applications",shared_css)
        self.assertIn("text-decoration: none",shared_css)
        self.assertIn(".nav-dropdown-item:focus-visible",shared_css)

    def test_security_uses_shared_settings_components_and_readonly_state(self):
        html = self.client.get("/settings/security").get_data(as_text=True)
        for marker in ("settings-main-layout", "settings-content-card", "form-grid-equal",
                       "checkbox-card", "Session Management", "Advanced Session / Cookie Settings",
                       "Save Security Settings"):
            self.assertIn(marker, html)
        with self.client.session_transaction() as data:
            data["user_permissions"] = ["launchpad.settings.security.view"]
        html = self.client.get("/settings/security").get_data(as_text=True)
        self.assertIn("Management permission is required", html)
        self.assertNotIn("Save Security Settings", html)

    def test_theme_endpoint_persists_all_modes_and_requires_csrf(self):
        for theme in ("light","dark","system"):
            response=self.client.post("/account/theme",data={"csrf_token":"test-csrf","theme_preference":theme})
            self.assertEqual(response.status_code,200)
            self.assertEqual(user_service.get_user_by_id(self.user["id"])["theme_preference"],theme)
        self.assertEqual(self.client.post("/account/theme",data={"theme_preference":"dark"}).status_code,400)

    def test_record_form_saves_friendly_name_and_creates_renewal(self):
        from apps.finance import routes
        with patch.object(routes,"maybe_send_renewal_notification_for_record",return_value=(False,"")):
            response=self.client.post("/finance/Technology/records/new",data={"title":"SOURCE TITLE", "friendly_name":"Friendly Record",
                "record_type":"software_license","status":"active","is_renewal":"on", "renewal_mode":"create", "csrf_token":"test-csrf"})
        self.assertEqual(response.status_code,302)
        with db.get_connection() as conn:
            record=dict(conn.execute("SELECT * FROM finance_records").fetchone())
        self.assertEqual(record_display_name(record),"Friendly Record")
        self.assertEqual(renewal_service.get_record_renewal_link(record["id"])["renewal_name"],"Friendly Record")


if __name__ == "__main__":
    unittest.main()
