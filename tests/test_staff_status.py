from __future__ import annotations

import gc
import sys
import tempfile
import types
import unittest
import warnings
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from flask import Flask
from jinja2 import Environment
from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

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
from apps.staff_status import leave_form_pdf
from apps.staff_status import vacation_personal_form_pdf
from apps.staff_status import routes as staff_status_routes
from apps.staff_status import service as staff_status_service
from apps.staff_status.blueprint import bp as staff_status_bp
from modules.core.auth import seed_permissions
from modules.core.identity import identity_db, rbac_db, rbac_service, user_service
from modules.core.settings import settings_db
from modules.core.settings.settings_service import set_setting
from tasks import scheduler as task_scheduler
from tasks.jobs.staff_status import get_staff_status_jobs


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
            "leave_form_dir": staff_status_service.LEAVE_FORM_DIR,
            "leave_form_template_path": staff_status_service.LEAVE_FORM_TEMPLATE_PATH,
            "vacation_personal_template_path": staff_status_service.VACATION_PERSONAL_FORM_TEMPLATE_PATH,
            "monthly_leave_form_dir": staff_status_service.MONTHLY_LEAVE_FORM_DIR,
        }

        staff_status_db.DATA_DIR = self.tmp_path
        staff_status_db.DB_PATH = self.tmp_path / "staff_status.db"
        staff_status_service.LEAVE_FORM_DIR = self.tmp_path / "generated_leave_forms"
        staff_status_service.MONTHLY_LEAVE_FORM_DIR = self.tmp_path / "monthly_leave_forms"
        request_template_path = self.tmp_path / "vacation_personal_request_form.pdf"
        request_template = canvas.Canvas(str(request_template_path), pagesize=letter, pageCompression=0)
        request_template.drawString(36, 750, "VACATION / PERSONAL REQUEST FORM")
        request_template.drawString(36, 720, "School Year")
        request_template.drawString(36, 690, "Employee's Name")
        request_template.drawString(400, 690, "Date")
        request_template.drawString(36, 665, "Position")
        request_template.drawString(370, 665, "Campus")
        request_template.drawString(190, 630, "PLEASE CIRCLE ONE: Vacation or Personal")
        request_template.drawString(36, 580, "Requested date(s)")
        request_template.drawString(36, 530, "Number of days currently available")
        request_template.drawString(36, 500, "Number of days requested on this form")
        request_template.drawString(36, 470, "Balance of vacation or personal days")
        request_template.drawString(36, 300, "Employee Signature")
        request_template.drawString(36, 250, "Supervisor Signature / Date")
        request_template.drawString(36, 200, "Superintendent Signature / Date")
        request_template.save()
        staff_status_service.VACATION_PERSONAL_FORM_TEMPLATE_PATH = request_template_path
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
        staff_status_service.LEAVE_FORM_DIR = self.original_paths["leave_form_dir"]
        staff_status_service.LEAVE_FORM_TEMPLATE_PATH = self.original_paths["leave_form_template_path"]
        staff_status_service.VACATION_PERSONAL_FORM_TEMPLATE_PATH = self.original_paths["vacation_personal_template_path"]
        staff_status_service.MONTHLY_LEAVE_FORM_DIR = self.original_paths["monthly_leave_form_dir"]
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

    def test_google_sync_interval_seconds_migrates_and_validates(self):
        set_setting("staff_status.absence_google_sync.interval_seconds", "")
        set_setting("staff_status.absence_google_sync.interval_minutes", "5")
        settings = google_absence_sync.get_google_absence_sync_settings()
        self.assertEqual(settings["interval_seconds"], 300)

        google_absence_sync.update_google_absence_sync_settings(
            enabled=False, spreadsheet_id="", worksheet_name="Absence Requests",
            interval_seconds=60, processing_timeout_minutes=15,
        )
        self.assertEqual(google_absence_sync.get_google_absence_sync_settings()["interval_seconds"], 60)
        for invalid in (0, -1, 29, 86401):
            with self.subTest(invalid=invalid), self.assertRaises(
                google_absence_sync.GoogleAbsenceSyncConfigurationError
            ):
                google_absence_sync.update_google_absence_sync_settings(
                    enabled=False, spreadsheet_id="", worksheet_name="Absence Requests",
                    interval_seconds=invalid, processing_timeout_minutes=15,
                )

        sync_job = next(job for job in get_staff_status_jobs() if job["job_id"] == "staff_status.google_absence_sync")
        self.assertEqual(sync_job["schedule_type"], "interval_seconds")
        self.assertEqual(sync_job["interval_default"], 60)
        self.assertEqual(task_scheduler._parse_interval_seconds("60"), 60)
        scheduler_source = (PROJECT_ROOT / "tasks" / "scheduler.py").read_text(encoding="utf-8")
        self.assertIn("IntervalTrigger(seconds=interval_seconds)", scheduler_source)
        self.assertIn("max_instances=1", scheduler_source)
        self.assertIn("coalesce=True", scheduler_source)

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

    def test_google_rejects_unconfigured_gmail_and_allows_configured_global_gmail(self):
        self._district_user()
        queue, _, _ = self._run_queue_sync([self._queue_row()])
        queue.rows[0].update({"workflow_status": "approved", "reviewed_by": "personal.reviewer@gmail.com",
                              "reviewed_at": "2026-09-15T14:05:00+00:00", "launchpad_sync_status": "pending"})
        result = google_absence_sync.sync_google_absence_requests(client=queue)
        record = staff_status_service.get_pending_absence_request_by_submission_uuid(queue.rows[0]["submission_uuid"])
        self.assertEqual(record["status"], "pending")
        self.assertIn("not authorized", queue.rows[0]["launchpad_sync_error"])
        set_setting("staff_status.absence_google_sync.global_reviewer_emails", "personal.reviewer@gmail.com")
        with patch.object(google_absence_sync, "send_absence_decision_result_email_once"):
            result = google_absence_sync.sync_google_absence_requests(client=queue)
        self.assertEqual(result["counts"]["decisions"], 1)
        record = staff_status_service.get_pending_absence_request_by_submission_uuid(queue.rows[0]["submission_uuid"])
        self.assertEqual(record["reviewed_by_email"], "personal.reviewer@gmail.com")

    def test_request_history_and_friendly_formatting(self):
        self._district_user()
        self._run_queue_sync([self._queue_row()])
        rows = staff_status_service.list_absence_requests_for_department("Technology", "pending")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date_range_label"], "Wednesday, September 16, 2026")
        self.assertIn(" at ", rows[0]["submitted_at_label"])
        self.assertRegex(rows[0]["submitted_at_label"], r"\d{1,2}:\d{2} [AP]M$")
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
        self.assertIsNone(send_mail.call_args.kwargs["attachments"])
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

    def test_absence_dashboard_defaults_requests_to_pending_and_skips_past_query(self):
        captured = {}

        def fake_render_template(template_name, **kwargs):
            captured.update(kwargs)
            return "ok"

        app = self.make_route_app()
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.admin_user["id"]
                session["user_permissions"] = ["staff_status.view", "staff_status.operator", "staff_status.admin"]
            with (
                patch.object(staff_status_routes, "render_template", side_effect=fake_render_template),
                patch.object(staff_status_routes, "list_absences_for_department", return_value=[]) as list_absences,
                patch.object(staff_status_routes, "list_absence_requests_for_department", return_value=[]) as list_requests,
            ):
                response = client.get("/staff-status/Technology/absences")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["current_request_status"], "pending")
        self.assertFalse(captured["past_absence_filters_applied"])
        self.assertEqual(captured["past_absences"], [])
        list_requests.assert_called_once_with("Technology", "pending")
        self.assertEqual([call.kwargs["timing"] for call in list_absences.call_args_list], ["upcoming"])

    def test_absence_request_status_filters_remain_available(self):
        app = self.make_route_app()
        expected_service_status = {"all": None, "pending": "pending", "approved": "approved", "denied": "denied"}
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.admin_user["id"]
                session["user_permissions"] = ["staff_status.view", "staff_status.operator", "staff_status.admin"]
            for requested_status, service_status in expected_service_status.items():
                captured = {}
                with (
                    patch.object(staff_status_routes, "render_template", side_effect=lambda _name, **kwargs: captured.update(kwargs) or "ok"),
                    patch.object(staff_status_routes, "list_absences_for_department", return_value=[]),
                    patch.object(staff_status_routes, "list_absence_requests_for_department", return_value=[]) as list_requests,
                ):
                    response = client.get(
                        "/staff-status/Technology/absences",
                        query_string={"request_status": requested_status},
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(captured["current_request_status"], requested_status)
                list_requests.assert_called_once_with("Technology", service_status)

    def test_past_absence_query_runs_after_explicit_range_and_supports_no_results(self):
        captured = {}

        def fake_list_absences_for_department(**kwargs):
            return []

        app = self.make_route_app()
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.admin_user["id"]
                session["user_permissions"] = ["staff_status.view", "staff_status.operator", "staff_status.admin"]
            with (
                patch.object(staff_status_routes, "render_template", side_effect=lambda _name, **kwargs: captured.update(kwargs) or "ok"),
                patch.object(staff_status_routes, "list_absences_for_department", side_effect=fake_list_absences_for_department) as list_absences,
            ):
                response = client.get(
                    "/staff-status/Technology/absences",
                    query_string={"table_date_range": "this_month"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(captured["past_absence_filters_applied"])
        self.assertEqual(captured["past_absences"], [])
        self.assertEqual([call.kwargs["timing"] for call in list_absences.call_args_list], ["upcoming", "past"])

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

    def test_leave_profile_decimal_balances_and_manual_audit(self):
        profile = staff_status_service.save_employee_leave_profile(
            user_id=self.tech_user["id"], department_name="Technology", employee_number="E-1007",
            balances={"sick": "10", "personal": "8.5", "vacation": "1.25"},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        self.assertEqual(profile["employee_number"], "E-1007")
        self.assertEqual(profile["balances"], {"sick": 10.0, "personal": 8.5, "vacation": 1.25})
        staff_status_service.save_employee_leave_profile(
            user_id=self.tech_user["id"], department_name="Technology", employee_number="E-1007",
            balances={"sick": "9.5", "personal": "8.5", "vacation": "1.25"},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        ledger = staff_status_service.list_leave_ledger_for_user(self.tech_user["id"])
        sick = next(row for row in ledger if row["leave_type"] == "sick")
        self.assertEqual(sick["balance_before"], 10.0)
        self.assertEqual(sick["balance_after"], 9.5)
        self.assertEqual(sick["transaction_type"], "manual_balance_set")
        for invalid in ("not-a-number", "nan"):
            with self.subTest(invalid=invalid), self.assertRaises(staff_status_service.StaffStatusValidationError):
                staff_status_service.save_employee_leave_profile(
                    user_id=self.tech_user["id"], department_name="Technology", employee_number="E-1007",
                    balances={"sick": invalid, "personal": 8.5, "vacation": 1.25},
                    actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
                )

    def test_canonical_monthly_leave_form_overlay(self):
        template_path = PROJECT_ROOT / "static" / "forms" / "employee_leave_form.pdf"
        self.assertEqual(staff_status_service.LEAVE_FORM_TEMPLATE_PATH, template_path)

        template = PdfReader(str(template_path))
        self.assertIsNone(template.get_fields())
        template_page = template.pages[0]
        template_text = template_page.extract_text()
        output_path = self.tmp_path / "monthly.pdf"
        leave_form_pdf.fill_monthly_employee_leave_form(
            template_path=template_path, output_path=output_path,
            employee_number="EMP-42", employee_name="Tech User", total_days_absent="4.75",
            classification_dates={
                "sick": "September 3, September 8-9, September 21",
                "personal": "September 14", "vacation": "September 28-30",
            },
        )
        output = PdfReader(str(output_path))
        output_page = output.pages[0]
        output_text = output_page.extract_text()
        self.assertEqual(output_page.mediabox, template_page.mediabox)
        self.assertIn("EMP-42", output_text)
        self.assertIn("Tech User", output_text)
        self.assertIn("4.75", output_text)
        self.assertIn("September 3", output_text)
        self.assertIn("September 14", output_text)
        self.assertIn("September 28-30", output_text)
        self.assertIn("EMPLOYEE SIGNATURE", output_text)
        self.assertTrue(set(template_text.splitlines()).issubset(set(output_text.splitlines())))
        missing_path = self.tmp_path / "missing-monthly-template.pdf"
        with self.assertRaises(leave_form_pdf.LeaveFormTemplateError):
            leave_form_pdf.fill_monthly_employee_leave_form(
                template_path=missing_path, output_path=self.tmp_path / "missing-monthly-output.pdf",
                employee_number="EMP-42", employee_name="Tech User", total_days_absent="1",
                classification_dates={"sick": "September 3", "personal": "", "vacation": ""},
            )
        self.assertFalse((self.tmp_path / "missing-monthly-output.pdf").exists())

    def test_missing_canonical_leave_form_template_fails_without_substitute(self):
        output_path = self.tmp_path / "must-not-exist.pdf"
        missing_path = self.tmp_path / "missing-vacation-personal-request-form.pdf"
        with self.assertRaises(leave_form_pdf.LeaveFormTemplateError) as error:
            vacation_personal_form_pdf.fill_vacation_personal_request_form(
                template_path=missing_path, output_path=output_path, leave_type="personal",
                school_year="2026-2027", employee_name="Tech User", request_date="September 1, 2026",
                position="Teacher", campus="Technology", requested_dates="September 17, 2026",
                balance_before="2", days_requested="1", balance_after="1",
            )
        self.assertIn(str(missing_path), str(error.exception))
        self.assertFalse(output_path.exists())

        staff_status_service.save_employee_leave_profile(
            user_id=self.tech_user["id"], department_name="Technology", employee_number="EMP-42",
            balances={"sick": 2, "personal": 2, "vacation": 2},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        staff_status_service.VACATION_PERSONAL_FORM_TEMPLATE_PATH = missing_path
        with patch.object(staff_status_service, "send_mail") as send_mail:
            absence = staff_status_service.create_absence(
                user_id=self.tech_user["id"], department_name="Technology", absence_type="personal",
                start_date="2026-09-17", end_date="2026-09-17", duration_mode="full_day",
                days_value=1, note="", created_by_user_id=self.admin_user["id"],
                created_by_display_name="Manager User", idempotency_key="missing-template-test",
            )
        send_mail.assert_not_called()
        self.assertEqual(absence["leave_result_email_status"], "error")
        self.assertIn(str(missing_path), absence["leave_result_email_error"])
        self.assertIsNone(absence["leave_form_generated_at"])
        self.assertFalse((staff_status_service.LEAVE_FORM_DIR / f"vacation-personal-request-form-{absence['id']}.pdf").exists())
        ledger = staff_status_service.list_leave_ledger_for_user(self.tech_user["id"])
        self.assertEqual(sum(row["transaction_type"] == "absence_deduction" for row in ledger), 1)

    def test_personal_absence_uses_request_form_email_and_idempotent_regeneration(self):
        staff_status_service.save_employee_leave_profile(
            user_id=self.tech_user["id"], department_name="Technology", employee_number="EMP-42",
            balances={"sick": 2, "personal": 3, "vacation": 4},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        staff_status_service.update_absence_form_integration_settings(
            approval_manager_email="manager@example.test", notification_sender_email="sender@example.test")
        with patch.object(staff_status_service, "send_mail") as send_mail:
            absence = staff_status_service.create_absence(
                user_id=self.tech_user["id"], department_name="Technology", absence_type="personal",
                start_date="2026-09-27", end_date="2026-09-27", duration_mode="full_day",
                days_value=99, note="", created_by_user_id=self.admin_user["id"],
                created_by_display_name="Manager User",
                idempotency_key="manual-test-absence",
            )
            duplicate = staff_status_service.create_absence(
                user_id=self.tech_user["id"], department_name="Technology", absence_type="personal",
                start_date="2026-09-27", end_date="2026-09-27", duration_mode="full_day",
                days_value=1, note="", created_by_user_id=self.admin_user["id"],
                created_by_display_name="Manager User", idempotency_key="manual-test-absence",
            )
            self.assertEqual(duplicate["id"], absence["id"])
            self.assertFalse(staff_status_service.send_approved_absence_email_once(absence["id"]))
        send_mail.assert_called_once()
        attachment = send_mail.call_args.kwargs["attachments"][0]
        attachment_path = Path(attachment["path"])
        pdf_bytes = attachment_path.read_bytes()
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertTrue(attachment_path.resolve().is_relative_to(staff_status_service.LEAVE_FORM_DIR.resolve()))
        pdf_text = PdfReader(str(attachment_path)).pages[0].extract_text()
        self.assertIn("Tech User", pdf_text)
        self.assertIn("VACATION / PERSONAL REQUEST FORM", pdf_text)
        self.assertIn("2026-2027", pdf_text)
        self.assertIn("September 27, 2026", pdf_text)
        self.assertIn("3", pdf_text)
        self.assertIn("2", pdf_text)
        self.assertEqual(set(vacation_personal_form_pdf.REQUEST_TYPE_MARKS), {"personal", "vacation"})
        saved = staff_status_service.get_absence_by_id(absence["id"])
        self.assertEqual(saved["leave_days_used"], 1.0)
        self.assertEqual(saved["leave_balance_before"], 3.0)
        self.assertEqual(saved["leave_balance_after"], 2.0)
        ledger = staff_status_service.list_leave_ledger_for_user(self.tech_user["id"])
        self.assertEqual(sum(row["transaction_type"] == "absence_deduction" for row in ledger), 1)
        send_mail.reset_mock()
        regenerated = staff_status_service.generate_vacation_personal_request_form(absence["id"], force=True)
        self.assertEqual(regenerated["path"].name, attachment_path.name)
        self.assertTrue(regenerated["path"].resolve().is_relative_to(staff_status_service.LEAVE_FORM_DIR.resolve()))
        send_mail.assert_not_called()
        ledger = staff_status_service.list_leave_ledger_for_user(self.tech_user["id"])
        self.assertEqual(sum(row["transaction_type"] == "absence_deduction" for row in ledger), 1)
        self.assertTrue(staff_status_service.delete_absence(
            absence_id=absence["id"], updated_by_user_id=self.admin_user["id"],
            updated_by_display_name="Manager User"))
        self.assertFalse(staff_status_service.delete_absence(
            absence_id=absence["id"], updated_by_user_id=self.admin_user["id"],
            updated_by_display_name="Manager User"))
        profile = staff_status_service.get_employee_leave_profile(self.tech_user["id"])
        self.assertEqual(profile["balances"]["personal"], 3.0)
        ledger = staff_status_service.list_leave_ledger_for_user(self.tech_user["id"])
        self.assertEqual(sum(row["transaction_type"] == "absence_reversal" for row in ledger), 1)

    def test_sick_absence_sends_approved_email_without_individual_pdf(self):
        staff_status_service.save_employee_leave_profile(
            user_id=self.tech_user["id"], department_name="Technology", employee_number="EMP-42",
            balances={"sick": 2, "personal": 2, "vacation": 2},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        with patch.object(staff_status_service, "send_mail") as send_mail:
            absence = staff_status_service.create_absence(
                user_id=self.tech_user["id"], department_name="Technology", absence_type="sick",
                start_date="2026-09-27", end_date="2026-09-27", duration_mode="full_day",
                days_value=1, note="", created_by_user_id=self.admin_user["id"],
                created_by_display_name="Manager User", idempotency_key="sick-without-form",
            )
        send_mail.assert_called_once()
        self.assertIsNone(send_mail.call_args.kwargs["attachments"])
        self.assertIsNone(absence["leave_form_generated_at"])
        self.assertIsNone(absence["leave_form_path"])

    def test_vacation_absence_generates_request_form_with_snapshotted_balances(self):
        staff_status_service.save_employee_leave_profile(
            user_id=self.tech_user["id"], department_name="Technology", employee_number="EMP-42",
            balances={"sick": 2, "personal": 2, "vacation": 4},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        with (
            patch.object(staff_status_service, "send_mail") as send_mail,
            patch.object(
                staff_status_service,
                "fill_vacation_personal_request_form",
                wraps=staff_status_service.fill_vacation_personal_request_form,
            ) as fill_form,
        ):
            absence = staff_status_service.create_absence(
                user_id=self.tech_user["id"], department_name="Technology", absence_type="vacation",
                start_date="2026-09-28", end_date="2026-09-28", duration_mode="full_day",
                days_value=1, note="", created_by_user_id=self.admin_user["id"],
                created_by_display_name="Manager User", idempotency_key="vacation-request-form",
            )
        self.assertEqual(fill_form.call_args.kwargs["leave_type"], "vacation")
        attachment = send_mail.call_args.kwargs["attachments"][0]
        pdf_page = PdfReader(str(attachment["path"])).pages[0]
        pdf_text = pdf_page.extract_text()
        self.assertIn("Tech User", pdf_text)
        self.assertIn("September 28, 2026", pdf_text)
        self.assertEqual(absence["leave_balance_before"], 4.0)
        self.assertEqual(absence["leave_days_used"], 1.0)
        self.assertEqual(absence["leave_balance_after"], 3.0)
        dynamic_positions = []
        pdf_page.extract_text(
            visitor_text=lambda text, cm, tm, font, size: dynamic_positions.append(
                (text.strip(), float(tm[5]))
            ) if text.strip() in {"Tech User", "September 28, 2026", "4", "1", "3"} else None
        )
        self.assertTrue(dynamic_positions)
        self.assertTrue(all(y > 349 for _, y in dynamic_positions))

    def test_request_form_coordinates_match_canonical_pdf(self):
        expected_positions = {
            "school_year": (289, 691, 95),
            "employee_name": (132, 578, 245),
            "request_date": (415, 578, 150),
            "position": (82, 545, 295),
            "campus": (432, 545, 135),
            "requested_dates": (317, 483, 245),
            "balance_before": (286, 453, 70),
            "days_requested": (285, 424, 70),
            "balance_after": (285, 396, 70),
        }
        actual_positions = {
            name: (position.x, position.y, position.max_width)
            for name, position in vacation_personal_form_pdf.REQUEST_FORM_FIELD_POSITIONS.items()
        }
        self.assertEqual(actual_positions, expected_positions)
        self.assertEqual(vacation_personal_form_pdf.REQUEST_TYPE_MARKS["vacation"], (151, 512, 51, 19))
        self.assertEqual(vacation_personal_form_pdf.REQUEST_TYPE_MARKS["personal"], (226, 512, 52, 19))

        template_path = PROJECT_ROOT / "static" / "forms" / "vacation_personal_request_form.pdf"
        output_path = self.tmp_path / "calibrated-request-form.pdf"
        source = PdfReader(str(template_path))
        vacation_personal_form_pdf.fill_vacation_personal_request_form(
            template_path=template_path, output_path=output_path, leave_type="personal",
            school_year="2026-2027", employee_name="Tech User",
            request_date="September 16, 2026", position="Teacher", campus="Technology",
            requested_dates="September 17-19, 2026", balance_before="4",
            days_requested="2.5", balance_after="1.5",
        )
        page = PdfReader(str(output_path)).pages[0]
        self.assertEqual(page.mediabox, source.pages[0].mediabox)
        text = page.extract_text()
        self.assertIn("Request for Personal or Vacation Form", " ".join(text.split()))
        self.assertIn("Tech User", text)
        self.assertIn("September 17-19, 2026", text)
        self.assertIn("Employee's Signature", " ".join(text.split()))
        observed = {}
        expected_values = {
            "2026-2027": "school_year", "Tech User": "employee_name",
            "September 16, 2026": "request_date", "Teacher": "position",
            "Technology": "campus", "September 17-19, 2026": "requested_dates",
            "4": "balance_before", "2.5": "days_requested", "1.5": "balance_after",
        }
        page.extract_text(
            visitor_text=lambda value, cm, tm, font, size: observed.update(
                {expected_values[value.strip()]: round(float(tm[5]), 1)}
            ) if value.strip() in expected_values else None
        )
        self.assertEqual(set(observed), set(expected_positions))
        for name, y in observed.items():
            self.assertAlmostEqual(y, expected_positions[name][1], delta=.5)

    def test_monthly_leave_forms_group_employees_and_do_not_mutate_accounting(self):
        staff_status_service.save_employee_leave_profile(
            user_id=self.tech_user["id"], department_name="Technology", employee_number="EMP-42",
            balances={"sick": 10, "personal": 5, "vacation": 8},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        staff_status_service.save_employee_leave_profile(
            user_id=self.admin_user["id"], department_name="Technology", employee_number="EMP-99",
            balances={"sick": 10, "personal": 5, "vacation": 8},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        absences = [
            (self.tech_user["id"], "sick", "2026-09-03", "2026-09-03", "full_day", 1),
            (self.tech_user["id"], "personal", "2026-09-14", "2026-09-14", "half_day", .5),
            (self.tech_user["id"], "vacation", "2026-09-28", "2026-09-30", "multi_day", 3),
            (self.admin_user["id"], "sick", "2026-09-08", "2026-09-09", "multi_day", 2),
            (self.tech_user["id"], "other", "2026-09-22", "2026-09-22", "full_day", 1),
            (self.tech_user["id"], "sick", "2026-10-02", "2026-10-02", "full_day", 1),
        ]
        with patch.object(staff_status_service, "send_mail"):
            for index, (user_id, leave_type, start, end, mode, days) in enumerate(absences):
                staff_status_service.create_absence(
                    user_id=user_id, department_name="Technology", absence_type=leave_type,
                    start_date=start, end_date=end, duration_mode=mode, days_value=days,
                    start_time="08:00" if mode == "half_day" else None,
                    note="", created_by_user_id=self.admin_user["id"],
                    created_by_display_name="Manager User", idempotency_key=f"monthly-{index}",
                )

        balances_before = {
            user_id: staff_status_service.get_employee_leave_profile(user_id)["balances"]
            for user_id in (self.tech_user["id"], self.admin_user["id"])
        }
        ledger_before = {
            user_id: len(staff_status_service.list_leave_ledger_for_user(user_id))
            for user_id in (self.tech_user["id"], self.admin_user["id"])
        }
        result = staff_status_service.generate_monthly_employee_leave_forms(
            department_name="Technology", month_value="2026-09"
        )
        self.assertEqual(result["employee_count"], 2)
        self.assertTrue(result["path"].resolve().is_relative_to(staff_status_service.MONTHLY_LEAVE_FORM_DIR.resolve()))
        with zipfile.ZipFile(result["path"]) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), 2)
            tech_name = next(name for name in names if "Tech-User" in name)
            extracted_path = self.tmp_path / "monthly-tech.pdf"
            extracted_path.write_bytes(archive.read(tech_name))
        monthly_text = PdfReader(str(extracted_path)).pages[0].extract_text()
        self.assertIn("EMP-42", monthly_text)
        self.assertIn("Tech User", monthly_text)
        self.assertIn("4.5", monthly_text)
        self.assertIn("September 3", monthly_text)
        self.assertIn("September 14", monthly_text)
        self.assertIn("September 28-30", monthly_text)
        self.assertNotIn("September 22", monthly_text)
        self.assertNotIn("October 2", monthly_text)
        for user_id in (self.tech_user["id"], self.admin_user["id"]):
            self.assertEqual(staff_status_service.get_employee_leave_profile(user_id)["balances"], balances_before[user_id])
            self.assertEqual(len(staff_status_service.list_leave_ledger_for_user(user_id)), ledger_before[user_id])

    def test_approved_request_negative_balance_is_snapshotted_and_idempotent(self):
        staff_status_service.save_employee_leave_profile(
            user_id=self.tech_user["id"], department_name="Technology", employee_number="EMP-9",
            balances={"sick": .5, "personal": 0, "vacation": 0},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        request_record, _ = staff_status_service.create_pending_absence_request_from_public_submission(payload={
            "submission_uuid": "negative-balance-request", "staff_email": "tech@example.test",
            "absence_type": "sick", "duration_mode": "full_day", "start_date": "2026-09-28"})
        with patch.object(staff_status_service, "send_mail"):
            approved = staff_status_service.approve_pending_absence_request(
                request_id=request_record["id"], reviewed_by_user_id=self.admin_user["id"],
                reviewed_by_display_name="Manager User")
        self.assertEqual(approved["leave_balance_before"], .5)
        self.assertEqual(approved["leave_balance_after"], -.5)
        self.assertIn("negative", approved["leave_balance_warning"].lower())
        ledger = staff_status_service.list_leave_ledger_for_user(self.tech_user["id"])
        self.assertEqual(sum(row["transaction_type"] == "absence_deduction" for row in ledger), 1)

    def test_denied_request_has_no_leave_side_effects(self):
        staff_status_service.save_employee_leave_profile(
            user_id=self.tech_user["id"], department_name="Technology", employee_number="EMP-10",
            balances={"sick": 3, "personal": 2, "vacation": 1},
            actor_user_id=self.admin_user["id"], actor_display_name="Manager User",
        )
        request_record, _ = staff_status_service.create_pending_absence_request_from_public_submission(payload={
            "submission_uuid": "denied-leave-request", "staff_email": "tech@example.test",
            "absence_type": "sick", "duration_mode": "full_day", "start_date": "2026-09-29"})
        denied = staff_status_service.reject_pending_absence_request(
            request_id=request_record["id"], reviewed_by_user_id=self.admin_user["id"],
            reviewed_by_display_name="Manager User")
        self.assertEqual(denied["status"], "rejected")
        self.assertIsNone(denied["created_absence_id"])
        self.assertIsNone(denied["leave_form_generated_at"])
        profile = staff_status_service.get_employee_leave_profile(self.tech_user["id"])
        self.assertEqual(profile["balances"]["sick"], 3.0)
        ledger = staff_status_service.list_leave_ledger_for_user(self.tech_user["id"])
        self.assertFalse(any(row["transaction_type"] == "absence_deduction" for row in ledger))

    def test_leave_balance_route_enforces_department_operator_permission(self):
        app = self.make_route_app()
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.tech_user["id"]
                session["user_permissions"] = ["staff_status.view"]
            denied = client.post("/staff-status/Technology/absences", data={
                "action": "save_leave_profile", "user_id": self.tech_user["id"],
                "employee_number": "NO", "balance_sick": "1", "balance_personal": "1", "balance_vacation": "1"})
        self.assertEqual(denied.status_code, 403)

        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.admin_user["id"]
                session["user_permissions"] = [
                    "staff_status.view", "staff_status.operator", "staff_status.admin"
                ]
            saved = client.post("/staff-status/Technology/absences", data={
                "action": "save_leave_profile", "user_id": self.tech_user["id"],
                "employee_number": "UI-100", "balance_sick": "8.5",
                "balance_personal": "2", "balance_vacation": "1.25"})
        self.assertEqual(saved.status_code, 302)
        self.assertIn("leave_balances=open", saved.headers["Location"])

    def test_monthly_leave_form_route_requires_department_operator(self):
        app = self.make_route_app()
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.tech_user["id"]
                session["user_permissions"] = ["staff_status.view"]
            denied = client.post(
                "/staff-status/Technology/absences/monthly-leave-forms",
                data={"month": "2026-09"},
            )
        self.assertEqual(denied.status_code, 403)

        with app.test_client() as client:
            with client.session_transaction() as session:
                session["is_authenticated"] = True
                session["user_id"] = self.admin_user["id"]
                session["user_permissions"] = [
                    "staff_status.view", "staff_status.operator", "staff_status.admin"
                ]
            empty = client.post(
                "/staff-status/Technology/absences/monthly-leave-forms",
                data={"month": "2026-09"},
            )
        self.assertEqual(empty.status_code, 302)

    def test_leave_balances_modal_uses_custom_unsaved_change_confirmation(self):
        template = (PROJECT_ROOT / "apps" / "staff_status" / "templates" / "staff_status" / "absences.html").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "apps" / "staff_status" / "static" / "staff_status.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "apps" / "staff_status" / "static" / "staff_status.css").read_text(encoding="utf-8")
        self.assertIn("Leave Balances", template)
        self.assertIn("You have unsaved changes. Discard them?", template)
        self.assertIn("Keep Editing", template)
        self.assertIn("Discard Changes", template)
        self.assertNotIn("confirm(", template)
        self.assertIn('aria-label="Open absence settings"', template)
        self.assertIn('class="btn btn-secondary staff-status-absence-settings-btn"', template)
        self.assertIn('<span>Settings</span>', template)
        self.assertIn('data-modal-open="monthly-leave-forms-modal"', template)
        self.assertNotIn("staff-status-absence-title-row", template)
        header_actions = template.index('class="page-header-actions"')
        settings_button = template.index('data-modal-open="leave-balances-modal"')
        self.assertGreater(settings_button, header_actions)
        self.assertIn("function resetState()", template)
        self.assertIn("forms.forEach(resetForm)", template)
        self.assertIn("staff-status:modal-opened", template)
        self.assertIn("staff-status:modal-closed", template)
        self.assertIn("staff-status:modal-opened", script)
        self.assertIn("staff-status:modal-closed", script)
        self.assertIn(':root[data-theme="dark"] .staff-status-leave-modal-card', styles)
        self.assertIn("--leave-list-columns: minmax(280px, 1.4fr) minmax(160px, .8fr) minmax(360px, 1.6fr) 72px", styles)
        self.assertIn("grid-template-columns: var(--leave-list-columns)", styles)
        self.assertIn("align-items: start", styles)
        self.assertIn(".staff-status-leave-summary { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; }", styles)
        self.assertIn(".staff-status-leave-actions { margin: 0; padding: 0; text-align: right; }", styles)
        settings_template = (PROJECT_ROOT / "apps" / "launchpad_ui" / "templates" / "launchpad_ui" / "settings" / "staff_status.html").read_text(encoding="utf-8")
        self.assertIn("Polling Interval (seconds)", settings_template)
        self.assertIn('name="absence_google_interval_seconds"', settings_template)
        self.assertNotIn("absence_google_interval_minutes", settings_template)


if __name__ == "__main__":
    unittest.main()
