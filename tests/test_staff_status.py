from __future__ import annotations

import gc
import sys
import tempfile
import types
import unittest
import warnings
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from flask import Flask
from jinja2 import Environment

warnings.simplefilter("ignore", ResourceWarning)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

for package_name, package_path in {
    "apps.staff_status": PROJECT_ROOT / "apps" / "staff_status",
    "modules.core": PROJECT_ROOT / "modules" / "core",
}.items():
    package = types.ModuleType(package_name)
    package.__path__ = [str(package_path)]
    sys.modules[package_name] = package

from apps.staff_status import db as staff_status_db
from apps.staff_status import google_absence_sync
from apps.staff_status import routes as staff_status_routes
from apps.staff_status import service as staff_status_service
from apps.staff_status.blueprint import bp as staff_status_bp
from modules.core.auth import seed_permissions
from modules.core.identity import identity_db, rbac_db, rbac_service, user_service
from modules.core.settings import settings_db
from modules.core.settings.settings_service import set_setting


class StaffStatusServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp_path = Path(self.tmpdir.name)

        self.original_paths = {
            "staff_status_data_dir": staff_status_db.DATA_DIR,
            "staff_status_db_path": staff_status_db.DB_PATH,
            "identity_data_dir": identity_db.DATA_DIR,
            "identity_db_path": identity_db.IDENTITY_DB_PATH,
            "settings_data_dir": settings_db.DATA_DIR,
            "settings_db_path": settings_db.SETTINGS_DB_PATH,
            "rbac_data_dir": rbac_db.DATA_DIR,
            "rbac_db_path": rbac_db.RBAC_DB_PATH,
        }

        staff_status_db.DATA_DIR = self.tmp_path
        staff_status_db.DB_PATH = self.tmp_path / "staff_status.db"
        identity_db.DATA_DIR = self.tmp_path
        identity_db.IDENTITY_DB_PATH = self.tmp_path / "identity.db"
        settings_db.DATA_DIR = self.tmp_path
        settings_db.SETTINGS_DB_PATH = self.tmp_path / "settings.db"
        rbac_db.DATA_DIR = self.tmp_path
        rbac_db.RBAC_DB_PATH = self.tmp_path / "rbac.db"

        identity_db.init_identity_db()
        settings_db.init_settings_db()
        rbac_db.init_rbac_db()
        staff_status_db.init_staff_status_db()
        seed_permissions.seed_permissions()

        set_setting("general.timezone", "America/Chicago")
        set_setting("general.public_base_url", "https://launchpad.example.test")

        self.tech_user = user_service.create_user({
            "email": "tech@example.test",
            "display_name": "Tech User",
            "first_name": "Tech",
            "last_name": "User",
            "department": "Technology",
            "is_active": 1,
        })
        self.hr_user = user_service.create_user({
            "email": "hr@example.test",
            "display_name": "HR User",
            "first_name": "HR",
            "last_name": "User",
            "department": "Human Resources",
            "is_active": 1,
        })
        self.admin_user = user_service.create_user({
            "email": "manager@example.test",
            "display_name": "Manager User",
            "department": "Technology",
            "is_active": 1,
        })
        rbac_service.assign_role_to_user(self.admin_user["id"], "staff_status_admin")

        staff_status_service.sync_departments_from_users()

    def tearDown(self):
        staff_status_db.DATA_DIR = self.original_paths["staff_status_data_dir"]
        staff_status_db.DB_PATH = self.original_paths["staff_status_db_path"]
        identity_db.DATA_DIR = self.original_paths["identity_data_dir"]
        identity_db.IDENTITY_DB_PATH = self.original_paths["identity_db_path"]
        settings_db.DATA_DIR = self.original_paths["settings_data_dir"]
        settings_db.SETTINGS_DB_PATH = self.original_paths["settings_db_path"]
        rbac_db.DATA_DIR = self.original_paths["rbac_data_dir"]
        rbac_db.RBAC_DB_PATH = self.original_paths["rbac_db_path"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()
        self.tmpdir.cleanup()

    def make_route_app(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.config["SERVER_NAME"] = "launchpad.example.test"
        app.register_blueprint(staff_status_bp)
        return app

    def test_department_availability_uses_table_after_legacy_migration(self):
        set_setting("staff_status.enabled_departments", "Technology")
        staff_status_service.migrate_legacy_enabled_departments_setting()

        enabled_names = [
            row["department_name"]
            for row in staff_status_service.list_enabled_departments()
        ]
        self.assertEqual(enabled_names, ["Technology"])

        staff_status_service.set_department_staff_status_enabled("Human Resources", True)
        staff_status_service.migrate_legacy_enabled_departments_setting()

        enabled_names = sorted(
            row["department_name"]
            for row in staff_status_service.list_enabled_departments()
        )
        self.assertEqual(enabled_names, ["Human Resources", "Technology"])

    def test_disabled_department_direct_route_returns_403(self):
        staff_status_service.set_department_staff_status_enabled("Human Resources", False)
        app = self.make_route_app()

        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.admin_user["id"]
                session["user_permissions"] = [
                    "staff_status.view",
                    "staff_status.operator",
                    "staff_status.admin",
                ]

            response = client.get("/staff-status/Human%20Resources/absences")

        self.assertEqual(response.status_code, 403)

    def test_partial_day_absence_requires_and_uses_start_time(self):
        with self.assertRaises(staff_status_service.StaffStatusValidationError):
            staff_status_service.create_absence(
                user_id=self.tech_user["id"],
                department_name="Technology",
                absence_type="personal",
                start_date="2026-08-31",
                end_date="2026-08-31",
                duration_mode="half_day",
                days_value=0.5,
                note="",
                created_by_user_id=self.admin_user["id"],
                created_by_display_name="Manager User",
            )

        absence = staff_status_service.create_absence(
            user_id=self.tech_user["id"],
            department_name="Technology",
            absence_type="personal",
            start_date="2026-08-31",
            end_date="2026-08-31",
            duration_mode="half_day",
            days_value=0.5,
            start_time="09:30",
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )

        tz = ZoneInfo("America/Chicago")
        self.assertFalse(
            staff_status_service.is_absence_effective_at(
                absence,
                datetime(2026, 8, 31, 9, 29, tzinfo=tz),
            )
        )
        self.assertTrue(
            staff_status_service.is_absence_effective_at(
                absence,
                datetime(2026, 8, 31, 9, 30, tzinfo=tz),
            )
        )
        self.assertFalse(
            staff_status_service.is_absence_effective_at(
                absence,
                datetime(2026, 8, 31, 13, 30, tzinfo=tz),
            )
        )
        self.assertEqual(
            staff_status_service.get_absence_time_window_label(absence),
            "9:30 AM - 1:30 PM",
        )

    def _configure_google_absence_sync(self):
        set_setting("staff_status.absence_google_sync.enabled", 1)
        set_setting("staff_status.absence_google_sync.spreadsheet_id", "test-sheet")
        set_setting("staff_status.absence_google_sync.worksheet_name", "Absence Requests")
        set_setting("staff_status.absence_google_sync.processing_timeout_minutes", "15")

    def _district_user(self, **overrides):
        values = {
            "email": "tech@sheridanschools.org",
            "display_name": "District Tech",
            "department": "Technology",
            "is_active": 1,
        }
        values.update(overrides)
        return user_service.create_user(values)

    def _queue_row(self, **overrides):
        row = {header: "" for header in google_absence_sync.QUEUE_HEADERS}
        row.update({
            "submission_uuid": "164a70c6-73d5-4e61-a312-cb9019f7f451",
            "submitted_at": "2026-09-15T12:00:00+00:00",
            "staff_email": "tech@sheridanschools.org",
            "absence_type": "sick",
            "duration_mode": "quarter_day",
            "start_date": "2026-09-16",
            "end_date": "2026-09-16",
            "start_time": "08:00",
            "processing_status": "pending",
            "processing_attempts": "0",
        })
        row.update(overrides)
        return row

    def _run_queue_sync(self, rows):
        class FakeQueue:
            def __init__(self, source_rows):
                self.rows = []
                self.updates = []
                for number, source in enumerate(source_rows, start=2):
                    item = dict(source)
                    item["_row_number"] = number
                    self.rows.append(item)

            def fetch_rows(self):
                return [dict(row) for row in self.rows]

            def fetch_row(self, row_number):
                return dict(self.rows[row_number - 2])

            def update_row(self, row_number, updates):
                self.rows[row_number - 2].update(updates)
                self.updates.append((row_number, dict(updates)))

        self._configure_google_absence_sync()
        queue = FakeQueue(rows)
        fixed_now = datetime(2026, 9, 15, 14, 0, tzinfo=ZoneInfo("UTC"))
        with patch.object(google_absence_sync, "send_pending_absence_request_email") as send_email:
            result = google_absence_sync.sync_google_absence_requests(client=queue, now=fixed_now)
        return queue, result, send_email

    def test_google_queue_import_resolves_active_user_current_department(self):
        self._district_user()
        queue, result, send_email = self._run_queue_sync([self._queue_row()])
        pending = staff_status_service.list_pending_absence_requests()
        self.assertEqual(result["counts"]["processed"], 1)
        self.assertEqual(pending[0]["department_name"], "Technology")
        self.assertEqual(queue.rows[0]["processing_status"], "processed")
        self.assertEqual(str(pending[0]["id"]), str(queue.rows[0]["launchpad_request_id"]))
        send_email.assert_called_once()

    def test_google_queue_rejects_inactive_user(self):
        self._district_user(is_active=0)
        queue, result, _ = self._run_queue_sync([self._queue_row()])
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertEqual(queue.rows[0]["processing_status"], "error")
        self.assertIn("could not be found", queue.rows[0]["processing_error"])

    def test_google_queue_rejects_missing_user(self):
        queue, result, _ = self._run_queue_sync([self._queue_row()])
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertEqual(queue.rows[0]["processing_status"], "error")

    def test_google_queue_uses_current_department_and_rejects_disabled_department(self):
        self._district_user(department="Human Resources")
        staff_status_service.set_department_staff_status_enabled("Human Resources", False)
        queue, result, _ = self._run_queue_sync([self._queue_row()])
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertIn("not available", queue.rows[0]["processing_error"])

    def test_google_queue_rejects_malformed_absence(self):
        self._district_user()
        queue, result, _ = self._run_queue_sync([self._queue_row(duration_mode="invented")])
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertEqual(queue.rows[0]["processing_attempts"], 1)

    def test_google_queue_duplicate_uuid_creates_one_pending_request(self):
        self._district_user()
        second = self._queue_row(processing_status="pending")
        queue, result, send_email = self._run_queue_sync([self._queue_row(), second])
        self.assertEqual(len(staff_status_service.list_pending_absence_requests()), 1)
        self.assertEqual(result["counts"]["duplicates"], 1)
        self.assertEqual([row["processing_status"] for row in queue.rows], ["processed", "processed"])
        send_email.assert_called_once()

    def test_google_queue_ignores_already_processed_row(self):
        queue, result, _ = self._run_queue_sync([self._queue_row(processing_status="processed")])
        self.assertEqual(result["counts"]["claimed"], 0)
        self.assertEqual(queue.updates, [])

    def test_google_queue_repairs_stale_row_after_partial_processing(self):
        self._district_user()
        payload = {
            "submission_uuid": "164a70c6-73d5-4e61-a312-cb9019f7f451",
            "staff_email": "tech@sheridanschools.org",
            "absence_type": "sick",
            "duration_mode": "quarter_day",
            "start_date": "2026-09-16",
            "end_date": "2026-09-16",
            "start_time": "08:00",
        }
        existing, _ = staff_status_service.create_pending_absence_request_from_public_submission(payload=payload)
        stale = self._queue_row(
            processing_status="processing",
            processing_started_at="2026-09-15T12:00:00+00:00",
            processing_attempts="1",
        )
        queue, result, send_email = self._run_queue_sync([stale])
        self.assertEqual(result["counts"]["duplicates"], 1)
        self.assertEqual(queue.rows[0]["processing_status"], "processed")
        self.assertEqual(queue.rows[0]["launchpad_request_id"], existing["id"])
        self.assertEqual(queue.rows[0]["processing_attempts"], 2)
        send_email.assert_not_called()

    def test_google_queue_rejects_non_district_email_and_records_safe_error(self):
        self._district_user()
        queue, result, _ = self._run_queue_sync([self._queue_row(staff_email="attacker@example.com")])
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertEqual(queue.rows[0]["processing_error"], "A valid district email is required.")
        self.assertNotIn("Traceback", queue.rows[0]["processing_error"])

    def test_google_remote_approval_is_idempotent_and_persists_reviewer(self):
        self._district_user()
        queue, _, _ = self._run_queue_sync([self._queue_row()])
        queue.rows[0].update({
            "workflow_status": "approved",
            "reviewed_by": "bjpullman@sheridanschools.org",
            "reviewed_at": "2026-09-15T14:05:00+00:00",
            "decision_note": "Approved remotely",
            "launchpad_sync_status": "pending",
        })
        with patch.object(google_absence_sync, "send_absence_decision_result_email_once") as result_email:
            first = google_absence_sync.sync_google_absence_requests(
                client=queue, now=datetime(2026, 9, 15, 14, 6, tzinfo=ZoneInfo("UTC")))
            second = google_absence_sync.sync_google_absence_requests(
                client=queue, now=datetime(2026, 9, 15, 14, 7, tzinfo=ZoneInfo("UTC")))
        record = staff_status_service.get_pending_absence_request_by_submission_uuid(
            queue.rows[0]["submission_uuid"])
        self.assertEqual(first["counts"]["decisions"], 1)
        self.assertEqual(second["counts"]["decisions"], 0)
        self.assertEqual(record["status"], "approved")
        self.assertEqual(record["reviewed_by_email"], "bjpullman@sheridanschools.org")
        self.assertEqual(record["review_source"], "google_apps_script")
        self.assertIsNotNone(record["created_absence_id"])
        self.assertEqual(result_email.call_count, 2)  # second call is a persisted-state no-op in production

    def test_google_remote_denial_creates_no_absence(self):
        self._district_user()
        queue, _, _ = self._run_queue_sync([self._queue_row()])
        queue.rows[0].update({"workflow_status": "denied", "reviewed_by": "bjpullman@sheridanschools.org",
                              "reviewed_at": "2026-09-15T14:05:00+00:00", "launchpad_sync_status": "pending"})
        with patch.object(google_absence_sync, "send_absence_decision_result_email_once"):
            google_absence_sync.sync_google_absence_requests(client=queue)
        record = staff_status_service.get_pending_absence_request_by_submission_uuid(queue.rows[0]["submission_uuid"])
        self.assertEqual(record["status"], "rejected")
        self.assertIsNone(record["created_absence_id"])
        self.assertEqual(queue.rows[0]["workflow_status"], "denied")

    def test_google_rejects_unauthorized_reviewer_and_allows_global_reviewer(self):
        self._district_user()
        queue, _, _ = self._run_queue_sync([self._queue_row()])
        queue.rows[0].update({"workflow_status": "approved", "reviewed_by": "other@sheridanschools.org",
                              "reviewed_at": "2026-09-15T14:05:00+00:00", "launchpad_sync_status": "pending"})
        result = google_absence_sync.sync_google_absence_requests(client=queue)
        record = staff_status_service.get_pending_absence_request_by_submission_uuid(queue.rows[0]["submission_uuid"])
        self.assertEqual(record["status"], "pending")
        self.assertIn("not authorized", queue.rows[0]["launchpad_sync_error"])
        set_setting("staff_status.absence_google_sync.global_reviewer_emails", "other@sheridanschools.org")
        with patch.object(google_absence_sync, "send_absence_decision_result_email_once"):
            result = google_absence_sync.sync_google_absence_requests(client=queue)
        self.assertEqual(result["counts"]["decisions"], 1)

    def test_request_history_and_friendly_formatting(self):
        self._district_user()
        self._run_queue_sync([self._queue_row()])
        rows = staff_status_service.list_absence_requests_for_department("Technology", "pending")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date_range_label"], "Wednesday, September 16, 2026")
        self.assertIn("2:", rows[0]["submitted_at_label"])
        self.assertNotIn("T", rows[0]["submitted_at_label"])

    def test_disabled_department_rejects_public_submission(self):
        staff_status_service.update_absence_form_integration_settings(
            approval_manager_email="manager@example.test",
            notification_sender_email="sender@example.test",
        )
        staff_status_service.set_department_staff_status_enabled("Human Resources", False)

        with self.assertRaises(staff_status_service.StaffStatusValidationError):
            staff_status_service.create_pending_absence_request_from_public_submission(
                payload={
                    "submission_uuid": "disabled-department",
                    "staff_email": "hr@example.test",
                    "absence_type": "sick",
                    "duration_mode": "full_day",
                    "start_date": "2026-09-01",
                }
            )

    def test_approval_creates_absence_once_and_preserves_start_time(self):
        request_record, created = staff_status_service.create_pending_absence_request_from_public_submission(
            payload={
                "submission_uuid": "approve-request",
                "staff_email": "tech@example.test",
                "absence_type": "vacation",
                "duration_mode": "summer_4_hours",
                "start_date": "2026-09-02",
                "start_time": "08:15",
                "note": "Summer hours",
            }
        )
        self.assertTrue(created)

        approved = staff_status_service.approve_pending_absence_request(
            request_id=request_record["id"],
            reviewed_by_user_id=self.admin_user["id"],
            reviewed_by_display_name="Manager User",
            decision_note="Approved",
        )

        self.assertEqual(approved["status"], "approved")
        absence = staff_status_service.get_absence_by_id(approved["created_absence_id"])
        self.assertEqual(absence["start_time"], "08:15")
        self.assertEqual(absence["duration_mode"], "summer_4_hours")

        with self.assertRaises(staff_status_service.PendingAbsenceRequestStateError):
            staff_status_service.approve_pending_absence_request(
                request_id=request_record["id"],
                reviewed_by_user_id=self.admin_user["id"],
                reviewed_by_display_name="Manager User",
            )

    def test_result_notification_sends_once_and_persists_retry_state(self):
        staff_status_service.update_absence_form_integration_settings(
            approval_manager_email="manager@example.test", notification_sender_email="sender@example.test")
        request_record, _ = staff_status_service.create_pending_absence_request_from_public_submission(payload={
            "submission_uuid": "result-email-request", "staff_email": "tech@example.test",
            "absence_type": "sick", "duration_mode": "full_day", "start_date": "2026-09-17"})
        approved = staff_status_service.approve_pending_absence_request(
            request_id=request_record["id"], reviewed_by_user_id=self.admin_user["id"],
            reviewed_by_display_name="Manager User", reviewed_by_email="manager@example.test")
        with patch.object(staff_status_service, "send_mail") as send_mail:
            self.assertTrue(staff_status_service.send_absence_decision_result_email_once(approved))
            self.assertFalse(staff_status_service.send_absence_decision_result_email_once(approved))
        send_mail.assert_called_once()
        saved = staff_status_service.get_pending_absence_request_by_id(approved["id"])
        self.assertEqual(saved["result_notification_status"], "sent")
        self.assertTrue(saved["result_notification_sent_at"])

    def test_pdf_export_builds_one_section_per_active_user(self):
        staff_status_service.create_absence(
            user_id=self.tech_user["id"],
            department_name="Technology",
            absence_type="sick",
            start_date="2026-09-03",
            end_date="2026-09-03",
            duration_mode="full_day",
            days_value=1.0,
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )

        captured = {}

        class FakeDoc:
            def __init__(self, buffer, **kwargs):
                self.buffer = buffer

            def build(self, story):
                captured["story"] = story
                self.buffer.write(b"%PDF-fake")

        with patch.object(staff_status_service, "SimpleDocTemplate", FakeDoc):
            content, filename = staff_status_service.build_absence_pdf_export(
                department_name="Technology",
                timing="all",
                absence_types=[],
                user_ids=[],
                start_date="2026-09-01",
                end_date="2026-09-30",
            )

        story_text = [
            item.getPlainText()
            for item in captured["story"]
            if hasattr(item, "getPlainText")
        ]

        self.assertEqual(content, b"%PDF-fake")
        self.assertEqual(filename, "technology-absences-2026-09-01-to-2026-09-30.pdf")
        self.assertIn("Tech User", story_text)
        self.assertIn("No absences", story_text)

        captured.clear()

        with patch.object(staff_status_service, "SimpleDocTemplate", FakeDoc):
            staff_status_service.build_absence_pdf_export(
                department_name="Technology",
                timing="all",
                absence_types=[],
                user_ids=[str(self.tech_user["id"])],
                start_date="2026-09-01",
                end_date="2026-09-30",
            )

        filtered_story_text = [
            item.getPlainText()
            for item in captured["story"]
            if hasattr(item, "getPlainText")
        ]

        self.assertIn("Tech User", filtered_story_text)
        self.assertNotIn("Manager User", filtered_story_text)

    def test_absence_table_filters_and_sorting_work_together(self):
        staff_status_service.create_absence(
            user_id=self.tech_user["id"],
            department_name="Technology",
            absence_type="sick",
            start_date="2099-01-03",
            end_date="2099-01-03",
            duration_mode="full_day",
            days_value=1.0,
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )
        staff_status_service.create_absence(
            user_id=self.admin_user["id"],
            department_name="Technology",
            absence_type="sick",
            start_date="2099-01-02",
            end_date="2099-01-02",
            duration_mode="full_day",
            days_value=1.0,
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )
        staff_status_service.create_absence(
            user_id=self.admin_user["id"],
            department_name="Technology",
            absence_type="vacation",
            start_date="2099-01-01",
            end_date="2099-01-01",
            duration_mode="full_day",
            days_value=1.0,
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )

        rows = staff_status_service.list_absences_for_department(
            department_name="Technology",
            timing="upcoming",
            absence_types=["sick"],
            start_date="2099-01-01",
            end_date="2099-01-31",
            sort_key="user",
            sort_direction="asc",
        )

        self.assertEqual([row["absence_type"] for row in rows], ["sick", "sick"])
        self.assertEqual([row["user_display_name"] for row in rows], ["Manager User", "Tech User"])

    def test_absence_dashboard_uses_table_params_independent_of_report_params(self):
        staff_status_service.create_absence(
            user_id=self.tech_user["id"],
            department_name="Technology",
            absence_type="sick",
            start_date="2000-01-04",
            end_date="2000-01-04",
            duration_mode="full_day",
            days_value=1.0,
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )
        staff_status_service.create_absence(
            user_id=self.admin_user["id"],
            department_name="Technology",
            absence_type="vacation",
            start_date="2000-01-05",
            end_date="2000-01-05",
            duration_mode="full_day",
            days_value=1.0,
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )
        staff_status_service.create_absence(
            user_id=self.tech_user["id"],
            department_name="Technology",
            absence_type="sick",
            start_date="2099-01-04",
            end_date="2099-01-04",
            duration_mode="full_day",
            days_value=1.0,
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )

        captured = {}

        def fake_render_template(template_name, **kwargs):
            captured["template_name"] = template_name
            captured["kwargs"] = kwargs
            return "ok"

        app = self.make_route_app()
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.admin_user["id"]
                session["user_permissions"] = [
                    "staff_status.view",
                    "staff_status.operator",
                    "staff_status.admin",
                ]

            with patch.object(staff_status_routes, "render_template", side_effect=fake_render_template):
                response = client.get(
                    "/staff-status/Technology/absences",
                    query_string={
                        "report_absence_type": "sick",
                        "report_user_ids": str(self.tech_user["id"]),
                        "report_date_range": "custom",
                        "report_start_date": "2000-01-01",
                        "report_end_date": "2000-01-31",
                        "table_absence_type": "vacation",
                        "table_user_ids": str(self.admin_user["id"]),
                        "table_date_range": "custom",
                        "table_start_date": "2000-01-01",
                        "table_end_date": "2000-01-31",
                        "table_sort": "user",
                        "table_direction": "desc",
                    },
                )

        kwargs = captured["kwargs"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["template_name"], "staff_status/absences.html")
        self.assertEqual(kwargs["current_table_absence_types"], ["vacation"])
        self.assertEqual(kwargs["current_table_user_ids"], [str(self.admin_user["id"])])
        self.assertEqual(kwargs["current_table_sort_key"], "user")
        self.assertEqual(kwargs["current_table_sort_direction"], "desc")
        self.assertEqual([row["absence_type"] for row in kwargs["upcoming_absences"]], ["sick"])
        self.assertEqual([row["absence_type"] for row in kwargs["past_absences"]], ["vacation"])
        self.assertIn("Type: Vacation", kwargs["active_table_filters"])

    def test_absence_export_ignores_table_filters_and_uses_report_filters(self):
        staff_status_service.create_absence(
            user_id=self.tech_user["id"],
            department_name="Technology",
            absence_type="sick",
            start_date="2099-02-04",
            end_date="2099-02-04",
            duration_mode="full_day",
            days_value=1.0,
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )
        staff_status_service.create_absence(
            user_id=self.admin_user["id"],
            department_name="Technology",
            absence_type="vacation",
            start_date="2099-02-05",
            end_date="2099-02-05",
            duration_mode="full_day",
            days_value=1.0,
            note="",
            created_by_user_id=self.admin_user["id"],
            created_by_display_name="Manager User",
        )

        app = self.make_route_app()
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.admin_user["id"]
                session["user_permissions"] = [
                    "staff_status.view",
                    "staff_status.operator",
                    "staff_status.admin",
                ]

            unfiltered_response = client.get(
                "/staff-status/Technology/absences/export",
                query_string={
                    "format": "csv",
                    "table_absence_type": "vacation",
                    "table_user_ids": str(self.admin_user["id"]),
                    "report_date_range": "custom",
                    "report_start_date": "2099-02-01",
                    "report_end_date": "2099-02-28",
                },
            )
            report_filtered_response = client.get(
                "/staff-status/Technology/absences/export",
                query_string={
                    "format": "csv",
                    "table_absence_type": "sick",
                    "report_absence_type": "vacation",
                    "report_date_range": "custom",
                    "report_start_date": "2099-02-01",
                    "report_end_date": "2099-02-28",
                },
            )

        unfiltered_csv = unfiltered_response.get_data(as_text=True)
        report_filtered_csv = report_filtered_response.get_data(as_text=True)

        self.assertEqual(unfiltered_response.status_code, 200)
        self.assertIn(",sick,", unfiltered_csv)
        self.assertIn(",vacation,", unfiltered_csv)
        self.assertEqual(report_filtered_response.status_code, 200)
        self.assertNotIn(",sick,", report_filtered_csv)
        self.assertIn(",vacation,", report_filtered_csv)

    def test_new_templates_parse(self):
        environment = Environment()

        template_paths = [
            PROJECT_ROOT / "apps" / "staff_status" / "templates" / "staff_status" / "absences.html",
            PROJECT_ROOT / "apps" / "staff_status" / "templates" / "staff_status" / "absence_request_review.html",
            PROJECT_ROOT / "apps" / "launchpad_ui" / "templates" / "launchpad_ui" / "settings" / "staff_status.html",
        ]

        for template_path in template_paths:
            with self.subTest(template=template_path.name):
                environment.parse(template_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
