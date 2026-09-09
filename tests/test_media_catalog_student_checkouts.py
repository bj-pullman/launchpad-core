from __future__ import annotations

import tempfile
import sys
import types
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]

for package_name, package_path in {
    "apps.snipeops": PROJECT_ROOT / "apps" / "snipeops",
    "modules.core": PROJECT_ROOT / "modules" / "core",
}.items():
    package = types.ModuleType(package_name)
    package.__path__ = [str(package_path)]
    sys.modules[package_name] = package

from apps.snipeops.media_catalog import media_catalog_db
from apps.snipeops.media_catalog import blueprint
from apps.snipeops.media_catalog import student_checkout_service as service
from modules.core.auth import seed_permissions


class StudentCheckoutServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = media_catalog_db.DB_PATH
        media_catalog_db.DB_PATH = Path(self.tmpdir.name) / "media_catalog.sqlite3"
        media_catalog_db.init_db()

        self.actor = {
            "id": 7,
            "email": "media@example.test",
            "display_name": "Media Specialist",
        }

        self.cart = {
            "id": 100,
            "asset_tag": "084236",
            "serial": "CARTSERIAL",
            "name": "Cart 084236",
            "model_name": "Chromebook Cart",
            "category_name": "Cart",
            "status_name": "Ready to Deploy",
            "location_name": "Library",
            "assigned_type": "",
            "assigned_id": None,
            "assigned_name": "",
        }

        self.device = {
            "id": 200,
            "asset_tag": "CB100",
            "serial": "SER100",
            "name": "Chromebook 100",
            "model_name": "Dell Chromebook",
            "category_name": "Chromebook",
            "status_name": "Ready to Deploy",
            "location_name": "Library",
            "assigned_type": "asset",
            "assigned_id": 100,
            "assigned_name": "Cart 084236",
        }

        media_catalog_db.claim_cart(
            cart_asset=self.cart,
            user=self.actor,
        )
        media_catalog_db.update_cart_metadata(
            cart_asset_id=100,
            owner_user_id=7,
            media_specialist_owner="Media Specialist",
            teacher_name="BJ Pullman",
            room_number="300",
        )

        self.patches = [
            patch.object(service, "get_setting", return_value="America/Chicago"),
            patch.object(service, "search_assets", return_value=[self.device]),
            patch.object(
                service,
                "get_asset",
                side_effect=lambda asset_id: {
                    100: self.cart,
                    200: self.device,
                }.get(int(asset_id)),
            ),
        ]

        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

        media_catalog_db.DB_PATH = self.original_db_path
        self.tmpdir.cleanup()

    def test_next_business_day_rules(self):
        cases = {
            date(2026, 8, 10): date(2026, 8, 11),  # Monday
            date(2026, 8, 11): date(2026, 8, 12),
            date(2026, 8, 12): date(2026, 8, 13),
            date(2026, 8, 13): date(2026, 8, 14),
            date(2026, 8, 14): date(2026, 8, 17),  # Friday
            date(2026, 8, 15): date(2026, 8, 17),  # Saturday
            date(2026, 8, 16): date(2026, 8, 17),  # Sunday
        }

        for checkout_day, expected_due in cases.items():
            with self.subTest(checkout_day=checkout_day):
                self.assertEqual(
                    service.calculate_next_business_day(checkout_day),
                    expected_due,
                )

    def test_overdue_rules(self):
        record = {
            "return_by_date": "2026-08-17",
            "returned_at": None,
        }

        self.assertFalse(service.is_checkout_overdue(record, today=date(2026, 8, 16)))
        self.assertFalse(service.is_checkout_overdue(record, today=date(2026, 8, 17)))
        self.assertTrue(service.is_checkout_overdue(record, today=date(2026, 8, 18)))
        self.assertEqual(service.days_overdue(record, today=date(2026, 8, 20)), 3)

        returned = {
            **record,
            "returned_at": "2026-08-20T12:00:00+00:00",
        }
        self.assertFalse(service.is_checkout_overdue(returned, today=date(2026, 8, 21)))

    @patch.object(service, "_now_utc", return_value=datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc))
    def test_create_checkout_preserves_cart_context_and_student_id_is_optional(self, _clock):
        checkout = service.create_student_checkout(
            actor_user=self.actor,
            identifier="CB100",
            student_name="John Smith",
            student_id="",
            now=datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(checkout["student_name"], "John Smith")
        self.assertEqual(checkout["student_id"], "")
        self.assertEqual(checkout["device_asset_id"], 200)
        self.assertEqual(checkout["original_cart_asset_id"], 100)
        self.assertEqual(checkout["original_cart_asset_tag"], "084236")
        self.assertEqual(checkout["original_cart_teacher_name"], "BJ Pullman")
        self.assertEqual(checkout["original_cart_room_number"], "300")
        self.assertEqual(checkout["return_by_date"], "2026-08-14")
        self.assertEqual(checkout["status"], service.ACTIVE_STATUS)

    def test_student_name_is_required(self):
        with self.assertRaises(service.StudentCheckoutError):
            service.create_student_checkout(
                actor_user=self.actor,
                identifier="CB100",
                student_name="",
            )

    def test_duplicate_active_checkout_is_rejected_until_returned(self):
        first = service.create_student_checkout(
            actor_user=self.actor,
            identifier="CB100",
            student_name="John Smith",
            now=datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc),
        )

        with self.assertRaises(service.StudentCheckoutDuplicateError):
            service.create_student_checkout(
                actor_user=self.actor,
                identifier="CB100",
                student_name="Jane Smith",
                now=datetime(2026, 8, 10, 16, 0, tzinfo=timezone.utc),
            )

        returned = service.return_student_checkout(
            checkout_id=first["id"],
            actor_user=self.actor,
            now=datetime(2026, 8, 10, 17, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(returned["status"], service.RETURNED_STATUS)
        self.assertTrue(returned["returned_at"])
        self.assertEqual(returned["return_actor_user_id"], 7)

        second = service.create_student_checkout(
            actor_user=self.actor,
            identifier="CB100",
            student_name="Jane Smith",
            now=datetime(2026, 8, 11, 15, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(second["student_name"], "Jane Smith")

        history = service.list_student_checkouts_for_scope(
            cart_asset_ids=[100],
            status_filter="all",
        )

        self.assertEqual(len(history), 2)
        self.assertEqual(
            sorted(item["student_name"] for item in history),
            ["Jane Smith", "John Smith"],
        )

    def test_manual_return_by_override(self):
        checkout = service.create_student_checkout(
            actor_user=self.actor,
            identifier="CB100",
            student_name="John Smith",
            return_by_date="2026-08-20",
            now=datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(checkout["return_by_date"], "2026-08-20")
        self.assertEqual(checkout["due_date_overridden"], 1)

    def test_active_filter_includes_overdue_unreturned_checkouts(self):
        checkout = service.create_student_checkout(
            actor_user=self.actor,
            identifier="CB100",
            student_name="John Smith",
            return_by_date="2000-01-04",
            now=datetime(2000, 1, 3, 15, 0, tzinfo=timezone.utc),
        )

        active_rows = service.list_student_checkouts_for_scope(
            cart_asset_ids=[100],
            status_filter="active",
            today=date(2000, 1, 5),
        )
        overdue_rows = service.list_student_checkouts_for_scope(
            cart_asset_ids=[100],
            status_filter="overdue",
            today=date(2000, 1, 5),
        )

        self.assertEqual([row["id"] for row in active_rows], [checkout["id"]])
        self.assertEqual([row["id"] for row in overdue_rows], [checkout["id"]])
        self.assertEqual(active_rows[0]["status"], service.OVERDUE_STATUS)

    def test_scope_is_enforced_for_checkout_creation(self):
        other_user = {
            "id": 8,
            "email": "other@example.test",
            "display_name": "Other User",
        }

        with self.assertRaises(service.StudentCheckoutPermissionError):
            service.create_student_checkout(
                actor_user=other_user,
                identifier="CB100",
                student_name="John Smith",
            )


class StudentCheckoutPermissionSeedTests(unittest.TestCase):
    def test_student_checkout_permission_is_created_and_assigned_to_media_specialists(self):
        created_permissions = []
        assigned_permissions = []

        with patch.object(seed_permissions, "create_role"), \
             patch.object(seed_permissions, "create_permission") as create_permission, \
             patch.object(seed_permissions, "assign_permission_to_role") as assign_permission:

            create_permission.side_effect = lambda key, name: created_permissions.append((key, name))
            assign_permission.side_effect = lambda role, key: assigned_permissions.append((role, key))

            seed_permissions.seed_permissions()

        self.assertIn(
            (
                service.STUDENT_CHECKOUT_PERMISSION,
                "Student Checkout Management",
            ),
            created_permissions,
        )
        self.assertIn(
            ("media_specialist", service.STUDENT_CHECKOUT_PERMISSION),
            assigned_permissions,
        )


class StudentCheckoutApiFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = media_catalog_db.DB_PATH
        media_catalog_db.DB_PATH = Path(self.tmpdir.name) / "media_catalog.sqlite3"
        media_catalog_db.init_db()

        self.actor = {
            "id": 7,
            "email": "media@example.test",
            "display_name": "Media Specialist",
        }
        self.other_user = {
            "id": 8,
            "email": "other@example.test",
            "display_name": "Other User",
        }

        self.cart = {
            "id": 100,
            "asset_tag": "084236",
            "serial": "CARTSERIAL",
            "name": "Cart 084236",
            "model_name": "Chromebook Cart",
            "category_name": "Cart",
            "status_name": "Ready to Deploy",
            "location_name": "Library",
            "assigned_type": "",
            "assigned_id": None,
            "assigned_name": "",
        }
        self.other_cart = {
            **self.cart,
            "id": 101,
            "asset_tag": "084237",
            "serial": "CARTSERIAL2",
            "name": "Cart 084237",
        }
        self.device = {
            "id": 200,
            "asset_tag": "CB100",
            "serial": "SER100",
            "name": "Chromebook 100",
            "model_name": "Dell Chromebook",
            "category_name": "Chromebook",
            "status_name": "Ready to Deploy",
            "location_name": "Library",
            "assigned_type": "asset",
            "assigned_id": 100,
            "assigned_name": "Cart 084236",
        }
        self.other_device = {
            **self.device,
            "id": 201,
            "asset_tag": "CB101",
            "serial": "SER101",
            "assigned_id": 101,
            "assigned_name": "Cart 084237",
        }
        self.assets = {
            100: self.cart,
            101: self.other_cart,
            200: self.device,
            201: self.other_device,
        }

        media_catalog_db.claim_cart(
            cart_asset=self.cart,
            user=self.actor,
        )
        media_catalog_db.update_cart_metadata(
            cart_asset_id=100,
            owner_user_id=7,
            media_specialist_owner="Media Specialist",
            teacher_name="BJ Pullman",
            room_number="300",
        )
        media_catalog_db.claim_cart(
            cart_asset=self.other_cart,
            user=self.other_user,
        )

        self.patches = [
            patch.object(service, "get_setting", return_value="America/Chicago"),
            patch.object(service, "search_assets", side_effect=self.search_assets),
            patch.object(service, "get_asset", side_effect=self.get_asset),
            patch.object(blueprint, "get_asset", side_effect=self.get_asset),
            patch.object(blueprint, "get_user_by_id", side_effect=self.get_user_by_id),
            patch.object(
                blueprint,
                "count_assets_assigned_to_assets",
                side_effect=self.count_assets_assigned_to_assets,
            ),
        ]

        for item in self.patches:
            item.start()

        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.app.register_blueprint(blueprint.bp)
        self.client = self.app.test_client()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

        media_catalog_db.DB_PATH = self.original_db_path
        self.tmpdir.cleanup()

    def get_asset(self, asset_id):
        return self.assets.get(int(asset_id))

    def get_user_by_id(self, user_id):
        users = {
            7: self.actor,
            8: self.other_user,
        }
        return users.get(int(user_id))

    def search_assets(self, query, limit=50):
        query = str(query or "").lower()
        rows = []

        for asset in self.assets.values():
            haystack = " ".join(
                str(asset.get(key) or "")
                for key in ("asset_tag", "serial", "name")
            ).lower()
            if query in haystack:
                rows.append(asset)

        return rows[:limit]

    def count_assets_assigned_to_assets(self, cart_ids):
        counts = {}
        normalized = {int(cart_id) for cart_id in cart_ids}

        for asset in self.assets.values():
            assigned_id = asset.get("assigned_id")
            if assigned_id is not None and int(assigned_id) in normalized:
                counts[int(assigned_id)] = counts.get(int(assigned_id), 0) + 1

        return counts

    def login(self, user_id=7, extra_permissions=None):
        permissions = {
            "snipeops.media_catalog.view",
            service.STUDENT_CHECKOUT_PERMISSION,
        }
        permissions.update(extra_permissions or [])

        with self.client.session_transaction() as session:
            session["is_authenticated"] = True
            session["user_id"] = user_id
            session["user_permissions"] = sorted(permissions)

    def test_checkout_create_is_immediately_visible_to_list_and_dashboard(self):
        self.login()

        created = self.client.post(
            "/snipeops/media-catalog/api/student-checkouts",
            json={
                "identifier": "CB100",
                "student_name": "John Smith",
            },
        )

        self.assertEqual(created.status_code, 200)
        checkout = created.get_json()["checkout"]

        active = self.client.get(
            "/snipeops/media-catalog/api/student-checkouts?status=active"
        ).get_json()
        self.assertEqual(
            [item["id"] for item in active["checkouts"]],
            [checkout["id"]],
        )

        dashboard = self.client.get(
            "/snipeops/media-catalog/api/dashboard"
        ).get_json()
        self.assertEqual(dashboard["summary"]["active_checkout_count"], 1)
        self.assertEqual(dashboard["summary"]["overdue_checkout_count"], 0)

    def test_return_immediately_updates_active_returned_and_dashboard_counts(self):
        self.login()
        checkout = service.create_student_checkout(
            actor_user=self.actor,
            identifier="CB100",
            student_name="John Smith",
        )

        returned = self.client.post(
            f"/snipeops/media-catalog/api/student-checkouts/{checkout['id']}/return",
            json={},
        )
        self.assertEqual(returned.status_code, 200)

        active = self.client.get(
            "/snipeops/media-catalog/api/student-checkouts?status=active"
        ).get_json()
        returned_rows = self.client.get(
            "/snipeops/media-catalog/api/student-checkouts?status=returned"
        ).get_json()
        dashboard = self.client.get(
            "/snipeops/media-catalog/api/dashboard"
        ).get_json()

        self.assertEqual(active["checkouts"], [])
        self.assertEqual(
            [item["id"] for item in returned_rows["checkouts"]],
            [checkout["id"]],
        )
        self.assertEqual(dashboard["summary"]["active_checkout_count"], 0)
        self.assertEqual(dashboard["summary"]["overdue_checkout_count"], 0)

    def test_overdue_dashboard_count_updates_after_return(self):
        self.login()
        checkout = service.create_student_checkout(
            actor_user=self.actor,
            identifier="CB100",
            student_name="Overdue Student",
            return_by_date="2000-01-04",
            now=datetime(2000, 1, 3, 15, 0, tzinfo=timezone.utc),
        )

        dashboard = self.client.get(
            "/snipeops/media-catalog/api/dashboard"
        ).get_json()
        active = self.client.get(
            "/snipeops/media-catalog/api/student-checkouts?status=active"
        ).get_json()
        overdue = self.client.get(
            "/snipeops/media-catalog/api/student-checkouts?status=overdue"
        ).get_json()

        self.assertEqual(dashboard["summary"]["active_checkout_count"], 1)
        self.assertEqual(dashboard["summary"]["overdue_checkout_count"], 1)
        self.assertEqual([item["id"] for item in active["checkouts"]], [checkout["id"]])
        self.assertEqual([item["id"] for item in overdue["checkouts"]], [checkout["id"]])

        returned = self.client.post(
            f"/snipeops/media-catalog/api/student-checkouts/{checkout['id']}/return",
            json={},
        )
        self.assertEqual(returned.status_code, 200)

        refreshed = self.client.get(
            "/snipeops/media-catalog/api/dashboard"
        ).get_json()
        self.assertEqual(refreshed["summary"]["active_checkout_count"], 0)
        self.assertEqual(refreshed["summary"]["overdue_checkout_count"], 0)

    def test_scoped_users_only_see_their_applicable_checkout_records(self):
        service.create_student_checkout(
            actor_user=self.actor,
            identifier="CB100",
            student_name="John Smith",
        )

        self.login(user_id=8)

        active = self.client.get(
            "/snipeops/media-catalog/api/student-checkouts?status=active"
        ).get_json()
        dashboard = self.client.get(
            "/snipeops/media-catalog/api/dashboard"
        ).get_json()

        self.assertEqual(active["checkouts"], [])
        self.assertEqual(dashboard["summary"]["active_checkout_count"], 0)
        self.assertEqual(dashboard["summary"]["overdue_checkout_count"], 0)


if __name__ == "__main__":
    unittest.main()
