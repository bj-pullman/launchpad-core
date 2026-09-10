from __future__ import annotations

import gc
import sys
import tempfile
import types
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from jinja2 import Environment, FileSystemLoader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for package_name, package_path in {
    "apps.snipeops": PROJECT_ROOT / "apps" / "snipeops",
    "modules.core": PROJECT_ROOT / "modules" / "core",
}.items():
    package = types.ModuleType(package_name)
    package.__path__ = [str(package_path)]
    sys.modules[package_name] = package

from apps.snipeops.media_catalog import blueprint, media_catalog_db
from apps.snipeops.snipe_catalog import catalog_db


def asset(
    asset_id: int,
    tag: str,
    serial: str,
    name: str,
    *,
    category: str = "Chromebook",
    model: str = "Dell Chromebook 3110",
    status: str = "Ready to Deploy",
    location: str = "Library",
    assigned_to: dict | None = None,
) -> dict:
    return {
        "id": asset_id,
        "asset_tag": tag,
        "serial": serial,
        "name": name,
        "model": {"id": asset_id + 1000, "name": model},
        "category": {"id": asset_id + 2000, "name": category},
        "status_label": {"id": 1, "name": status},
        "location": {"id": 1, "name": location},
        "assigned_to": assigned_to,
    }


class AssetCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_catalog_path = catalog_db.DB_PATH
        self.original_media_path = media_catalog_db.DB_PATH
        catalog_db.DB_PATH = Path(self.tmpdir.name) / "catalog.sqlite3"
        media_catalog_db.DB_PATH = Path(self.tmpdir.name) / "media.sqlite3"
        catalog_db.init_db()
        media_catalog_db.init_db()

        rows = [
            asset(100, "CART100", "CART-SER-100", "Library Cart", category="Cart", model="Chromebook Cart"),
            asset(101, "CART101", "CART-SER-101", "Science Cart", category="Cart", model="Chromebook Cart", location="Science"),
            asset(102, "CART102", "CART-SER-102", "Unassigned Cart", category="Cart", model="Chromebook Cart", location="Warehouse"),
            asset(200, "CB100", "SER-EXACT-100", "Chromebook Alpha"),
            asset(201, "CB101", "SER-SAME-101", "Chromebook Same Assignment", assigned_to={"id": 100, "type": "asset", "name": "Library Cart"}),
            asset(202, "CB102", "SER-MOVE-102", "Chromebook Other Assignment", assigned_to={"id": 101, "type": "asset", "name": "Science Cart"}),
            asset(203, "CB103", "SER-USER-103", "Chromebook Assigned User", assigned_to={"id": 77, "type": "user", "name": "Taylor Teacher"}),
            asset(204, "CB104", "SER-RETIRED-104", "Retired Chromebook", status="Archived"),
        ]
        catalog_db.upsert_assets(rows)

        self.actor = {"id": 7, "email": "media@example.test", "display_name": "Media Specialist"}
        self.other = {"id": 8, "email": "other@example.test", "display_name": "Other Specialist"}
        media_catalog_db.claim_cart(cart_asset=catalog_db.get_asset(100), user=self.actor)
        media_catalog_db.claim_cart(cart_asset=catalog_db.get_asset(101), user=self.other)

        self.patches = [
            patch.object(
                blueprint,
                "get_user_by_id",
                side_effect=lambda user_id: {7: self.actor, 8: self.other}.get(int(user_id)),
            ),
            patch.object(blueprint, "checkout_asset_to_cart", return_value={"status": "success"}),
            patch.object(blueprint, "checkin_asset", return_value={"status": "success"}),
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
        catalog_db.DB_PATH = self.original_catalog_path
        media_catalog_db.DB_PATH = self.original_media_path
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()
        self.tmpdir.cleanup()

    def login(self, *, user_id: int = 7, manage: bool = True, global_manager: bool = False,
              snipeops_manager: bool = False):
        permissions = ["snipeops.media_catalog.view"]
        if manage:
            permissions.append("snipeops.media_catalog.manage")
        if global_manager:
            permissions.append("snipeops.media_catalog.ownership.manage")
        if snipeops_manager:
            permissions.append("snipeops.home.manage")
        with self.client.session_transaction() as data:
            data.update(
                is_authenticated=True,
                user_id=user_id,
                user_permissions=permissions,
            )

    def test_exact_asset_tag_serial_partial_and_no_result_search(self):
        by_tag = catalog_db.search_asset_catalog("CB100")
        self.assertEqual(by_tag["results"][0]["id"], 200)
        by_serial = catalog_db.search_asset_catalog("SER-EXACT-100")
        self.assertEqual(by_serial["results"][0]["id"], 200)
        partial = catalog_db.search_asset_catalog("chromebook")
        self.assertGreaterEqual(partial["total"], 4)
        assigned_user = catalog_db.search_asset_catalog("Taylor")
        self.assertEqual([row["id"] for row in assigned_user["results"]], [203])
        cart_tag = catalog_db.search_asset_catalog("CART101")
        self.assertIn(202, [row["id"] for row in cart_tag["results"]])
        self.assertEqual(catalog_db.search_asset_catalog("does-not-exist")["results"], [])

    def test_asset_catalog_tab_modal_and_client_workflow_are_present(self):
        template = (PROJECT_ROOT / "apps/snipeops/media_catalog/templates/media_catalog/index.html").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "apps/snipeops/media_catalog/static/js/media_catalog.js").read_text(encoding="utf-8")
        stylesheet = (PROJECT_ROOT / "apps/snipeops/media_catalog/static/css/media_catalog.css").read_text(encoding="utf-8")
        for marker in ("data-tab=\"asset-catalog\"", "assetCatalogSearchForm", "assetCatalogCartModal", "Add Asset to Cart"):
            self.assertIn(marker, template)
        for marker in ("searchAssetCatalog", "searchAssetCatalogCarts", "confirmAssetCatalogAdd"):
            self.assertIn(marker, script)
        self.assertIn(".asset-catalog-table", stylesheet)
        environment = Environment(loader=FileSystemLoader([
            PROJECT_ROOT / "templates",
            PROJECT_ROOT / "apps/snipeops/templates",
            PROJECT_ROOT / "apps/snipeops/media_catalog/templates",
        ]))
        environment.get_template("media_catalog/index.html")

    def test_catalog_api_requires_view_permission_and_returns_context(self):
        self.login(manage=False)
        response = self.client.get("/snipeops/media-catalog/api/asset-catalog?q=CB101")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["results"][0]["current_cart"]["id"], 100)
        self.assertFalse(payload["results"][0]["can_add_to_cart"])
        with self.client.session_transaction() as data:
            data["user_permissions"] = []
        self.assertEqual(
            self.client.get("/snipeops/media-catalog/api/asset-catalog?q=CB101").status_code,
            403,
        )

    def test_standard_cart_picker_is_owned_scope_and_global_manager_sees_all(self):
        self.login()
        owned = self.client.get("/snipeops/media-catalog/api/asset-catalog/carts").get_json()
        self.assertEqual(owned["scope"], "owned")
        self.assertEqual([cart["id"] for cart in owned["carts"]], [100])

        self.login(global_manager=True)
        all_carts = self.client.get("/snipeops/media-catalog/api/asset-catalog/carts").get_json()
        self.assertEqual(all_carts["scope"], "all")
        self.assertEqual({cart["id"] for cart in all_carts["carts"]}, {100, 101, 102})
        owner_search = self.client.get(
            "/snipeops/media-catalog/api/asset-catalog/carts?q=Other"
        ).get_json()
        self.assertEqual([cart["id"] for cart in owner_search["carts"]], [101])

        self.login(snipeops_manager=True)
        manager_scope = self.client.get(
            "/snipeops/media-catalog/api/asset-catalog/carts?q=CART102"
        ).get_json()
        self.assertEqual(manager_scope["scope"], "all")
        self.assertEqual([cart["id"] for cart in manager_scope["carts"]], [102])

    def test_server_rejects_view_only_and_unauthorized_cart_target(self):
        self.login(manage=False)
        self.assertEqual(
            self.client.post("/snipeops/media-catalog/api/add-to-cart", json={"cart_id": 100, "device_id": 200}).status_code,
            403,
        )
        self.login()
        response = self.client.post(
            "/snipeops/media-catalog/api/add-to-cart",
            json={"cart_id": 101, "device_id": 200},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(blueprint.checkout_asset_to_cart.call_count, 0)

    def test_same_cart_does_not_duplicate_or_write_history(self):
        self.login()
        response = self.client.post(
            "/snipeops/media-catalog/api/add-to-cart",
            json={"cart_id": 100, "device_id": 201},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["moved"])
        self.assertEqual(blueprint.checkout_asset_to_cart.call_count, 0)
        self.assertEqual(media_catalog_db.get_recent(), [])

    def test_add_available_asset_updates_cache_and_writes_history(self):
        self.login()
        response = self.client.post(
            "/snipeops/media-catalog/api/add-to-cart",
            json={"cart_id": 100, "device_id": 200},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["moved"])
        self.assertEqual(catalog_db.get_asset(200)["assigned_id"], 100)
        audit = media_catalog_db.get_recent()
        self.assertEqual(audit[0]["action"], "added_to_cart")
        self.assertEqual(audit[0]["actor_user_id"], 7)

    def test_cross_cart_move_requires_confirmation_and_creates_audit_entry(self):
        self.login()
        path = "/snipeops/media-catalog/api/add-to-cart"
        first = self.client.post(path, json={"cart_id": 100, "device_id": 202})
        self.assertEqual(first.status_code, 409)
        self.assertTrue(first.get_json()["confirmation_required"])
        self.assertEqual(blueprint.checkin_asset.call_count, 0)

        moved = self.client.post(
            path,
            json={"cart_id": 100, "device_id": 202, "confirm_move": True},
        )
        self.assertEqual(moved.status_code, 200)
        self.assertTrue(moved.get_json()["moved"])
        self.assertEqual(blueprint.checkin_asset.call_count, 1)
        self.assertEqual(blueprint.checkout_asset_to_cart.call_count, 1)
        updated = catalog_db.get_asset(202)
        self.assertEqual(updated["assigned_id"], 100)
        audit = media_catalog_db.get_recent()
        self.assertEqual(audit[0]["action"], "moved_to_cart")
        self.assertEqual(audit[0]["actor_user_id"], 7)
        self.assertIn("Science Cart", audit[0]["message"])
        self.assertIn("Library Cart", audit[0]["message"])

    def test_incompatible_user_assignment_is_rejected_before_snipe_it(self):
        self.login()
        response = self.client.post(
            "/snipeops/media-catalog/api/add-to-cart",
            json={"cart_id": 100, "device_id": 203},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("appropriate Snipe-IT workflow", response.get_json()["error"])
        self.assertEqual(blueprint.checkin_asset.call_count, 0)

    def test_missing_non_cart_and_archived_targets_are_rejected(self):
        self.login(global_manager=True)
        path = "/snipeops/media-catalog/api/add-to-cart"
        self.assertEqual(self.client.post(path, json={"cart_id": 999, "device_id": 200}).status_code, 404)
        self.assertEqual(self.client.post(path, json={"cart_id": 100, "device_id": 999}).status_code, 404)
        self.assertEqual(self.client.post(path, json={"cart_id": 200, "device_id": 203}).status_code, 400)
        archived = self.client.post(path, json={"cart_id": 100, "device_id": 204})
        self.assertEqual(archived.status_code, 409)
        self.assertIn("Archived", archived.get_json()["error"])
        self.assertEqual(blueprint.checkout_asset_to_cart.call_count, 0)


if __name__ == "__main__":
    unittest.main()
