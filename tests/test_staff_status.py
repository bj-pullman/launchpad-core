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

from apps.staff_status import api_routes as staff_status_api_routes
from apps.staff_status import db as staff_status_db
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

    def make_api_app(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.config["SERVER_NAME"] = "launchpad.example.test"
        app.register_blueprint(staff_status_api_routes.staff_status_integrations_bp)
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

    def test_integration_api_auth_and_idempotency(self):
        secret = staff_status_service.generate_absence_form_integration_secret()["raw_secret"]
        staff_status_service.update_absence_form_integration_settings(
            enabled=True,
            apps_script_url="https://script.google.com/macros/s/test/exec",
            approval_manager_email="manager@example.test",
            notification_sender_email="sender@example.test",
        )
        app = self.make_api_app()
        payload = {
            "submission_uuid": "same-request-id",
            "staff_email": "tech@example.test",
            "absence_type": "sick",
            "duration_mode": "quarter_day",
            "start_date": "2026-09-01",
            "start_time": "10:00",
            "note": "Morning appointment",
        }

        with app.test_client() as client:
            missing_auth = client.post(
                "/api/integrations/staff-status/absence-requests",
                json=payload,
            )
            self.assertEqual(missing_auth.status_code, 401)

            with patch.object(
                staff_status_api_routes,
                "send_pending_absence_request_email",
                return_value=None,
            ) as send_email:
                first = client.post(
                    "/api/integrations/staff-status/absence-requests",
                    json=payload,
                    headers={"Authorization": f"Bearer {secret}"},
                )
                second = client.post(
                    "/api/integrations/staff-status/absence-requests",
                    json=payload,
                    headers={"Authorization": f"Bearer {secret}"},
                )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.get_json()["duplicate"])
        self.assertTrue(second.get_json()["duplicate"])
        self.assertEqual(send_email.call_count, 1)

        pending = staff_status_service.list_pending_absence_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["start_time"], "10:00")

    def test_disabled_department_rejects_public_submission(self):
        staff_status_service.update_absence_form_integration_settings(
            enabled=True,
            apps_script_url="",
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
