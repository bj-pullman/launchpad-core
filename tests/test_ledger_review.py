"""Ledger review regressions; all database writes use disposable fixtures."""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import test_launchpad_workflows as fixtures
from apps.finance import db, service, ledger_import_service as importer
from apps.finance import ledger_review_service as review
from apps.finance import record_workflow_service as workflow
from apps.finance import record_workflow_routes as routes


class ReviewQueryTests(fixtures.IsolatedDatabases):
    def new_run(self):
        return service.create_import_run(import_type="transactions", source_type="erp_audit_trail",
                                         stored_filename="fixture.csv")

    def import_data(self, rows, run_id):
        with patch.object(importer, "read_import_rows", return_value=rows), \
             patch.object(importer, "_mapped_row", side_effect=lambda row, *args: row):
            result = importer.execute_ledger_import(run_id=run_id, default_department_name="Technology")
        self.assertEqual(result["error_rows"], 0)
        return result

    def test_pagination_and_combined_filters_cover_complete_dataset(self):
        ids = []
        for i in range(107):
            ids.append(self.ledger(source_hash=f"match-{i}", po_number=f"PO-{i}",
                                   account_code="6100", description="Device support", vendor_name="Target vendor"))
        self.ledger(source_hash="outside", vendor_name="Other", account_code="9999")
        self.ledger(source_hash="other-dept", department_name="Other", vendor_name="Target vendor", account_code="6100")
        filters = dict(fiscal_year_code="FY27", transaction_code="20", vendor_q="Target",
                       account_q="6100", po_number="PO-", q="support", review_status="unresolved")
        for size in review.PAGE_SIZES:
            found = []
            first = review.review_page("Technology", filters=filters, per_page=size)
            self.assertEqual(first["total"], 107)
            for page in range(1, first["total_pages"] + 1):
                result = review.review_page("Technology", filters=filters, per_page=size, page=page)
                found.extend(row["id"] for row in result["rows"])
            self.assertEqual(set(found), set(ids))
            self.assertEqual(len(found), 107)
            self.assertEqual(review.review_page("Technology", filters=filters, per_page=size, page=999)["page"], first["total_pages"])
        empty = review.review_page("Technology", filters={"q": "no such data"}, page=99)
        self.assertEqual((empty["total"], empty["page"], empty["first"], empty["last"]), (0, 1, 0, 0))

    def test_record_choices_are_real_searchable_paged_and_department_scoped(self):
        vendor = service.create_vendor(vendor_name="Source Vendor", friendly_name="Friendly Vendor")
        ids = [self.record(title=f"License {i:03}", friendly_name=f"Friendly {i:03}",
                           po_number=f"PO{i}", vendor_id=vendor) for i in range(56)]
        self.record(department_name="Other", title="Private")
        archived = self.record(title="Archived")
        with db.get_connection() as conn:
            conn.execute("UPDATE finance_records SET status='archived' WHERE id=?", (archived,))
        one = review.record_choices("Technology")
        two = review.record_choices("Technology", page=2)
        self.assertTrue(one["has_more"])
        self.assertFalse(two["has_more"])
        self.assertEqual([r["id"] for r in one["rows"] + two["rows"]], ids)
        for query in ("Friendly 055", "License 055", "PO55"):
            self.assertEqual(review.record_choices("Technology", query)["rows"][0]["id"], ids[-1])
        self.assertEqual(len(review.record_choices("Technology", "Friendly Vendor")["rows"]), 50)
        self.assertEqual(review.record_choices("Technology", "Private")["rows"], [])
        all_choices = review.record_choices("Technology", all_records=True)
        self.assertEqual([row["id"] for row in all_choices["rows"]], ids)
        self.assertFalse(all_choices["has_more"])
        self.assertEqual(len(review.record_choices("Technology", "Friendly Vendor", all_records=True)["rows"]), 56)

    def test_original_snapshot_survives_actions_rerun_and_reassignment(self):
        self.record(po_number="AUTO", title="Auto matched")
        self.record(po_number="AMBIG", title="Duplicate A")
        self.record(po_number="AMBIG", title="Duplicate B")
        rows = [dict(transaction_code="20", vendor_name="Vendor", po_number=po,
                     purchase_date="2026-08-01", description=f"Payment {po}", expenditure_amount="10")
                for po in ("AUTO", "AMBIG", "REVIEW")]
        run_id = self.new_run()
        self.import_data(rows, run_id)
        original_notes = service.get_import_run_by_id(run_id)["run_notes"]
        original = review.read_original_snapshot(service.get_import_run_by_id(run_id))
        counts = original["departments"]["Technology"]
        self.assertEqual((counts["inserted"], counts["auto_linked"], counts["unresolved"], counts["possible"]), (3, 1, 2, 1))
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM finance_ledger_transactions WHERE po_number='REVIEW'").fetchone()
        workflow.review_action("Technology", row["id"], "reviewed", 1)
        self.assertEqual(service.get_import_run_by_id(run_id)["run_notes"], original_notes)
        context = review.get_import_context("Technology", run_id)
        self.assertEqual(review.review_counts("Technology", context)["unresolved"], 1)
        self.import_data(rows, run_id)
        self.assertEqual(review.read_original_snapshot(service.get_import_run_by_id(run_id)), original)
        service.update_import_run_status(run_id, status="mapping_saved", run_notes="Mapping saved for validation.")
        self.assertEqual(review.read_original_snapshot(service.get_import_run_by_id(run_id)), original)
        second_run = self.new_run()
        self.import_data(rows, second_run)
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_ledger_transactions").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_ledger_transactions WHERE import_run_id=?", (run_id,)).fetchone()[0], 0)
        context = review.get_import_context("Technology", run_id)
        self.assertEqual(review.review_counts("Technology", context)["unresolved"], 1)
        self.assertEqual(review.review_page("Technology", import_context=context)["total"], 1)
        self.assertEqual(review.read_original_snapshot(service.get_import_run_by_id(run_id)), original)

    def test_legacy_summary_does_not_invent_original_statuses(self):
        run_id = self.new_run()
        self.ledger(import_run_id=run_id)
        service.update_import_run_results(run_id, status="completed", total_rows=12,
            created_rows=10, updated_rows=9, skipped_rows=2, error_rows=0,
            run_notes="Ledger import completed. Linked to records: 7, Records refreshed: 2.", completed=True)
        context = review.get_import_context("Technology", run_id)
        original = context["original"]
        self.assertEqual((original["inserted"], original["linked"]), (10, 7))
        self.assertIsNone(original["auto_linked"])
        self.assertIsNone(original["unresolved"])
        self.assertFalse(context["exact_membership"])
        with self.assertRaises(ValueError):
            review.get_import_context("Other", run_id)

    def test_import_links_payments_regardless_of_original_encumbrance_order(self):
        for index, reverse in enumerate((False, True)):
            with self.subTest(reverse=reverse):
                po = f"ORDER{index}"
                rows = [dict(transaction_code="20", vendor_name="Order Vendor", po_number=po + "-01",
                             description="Payment", purchase_date="2026-08-01", expenditure_amount="50"),
                        dict(transaction_code="17", vendor_name="Order Vendor", po_number=po + "-02",
                             description="Original encumbrance", purchase_date="2026-07-01", encumbrance_amount="100")]
                if reverse:
                    rows.reverse()
                run_id = self.new_run()
                result = self.import_data(rows, run_id)
                self.assertEqual(result["auto_created_records"], 1)
                self.assertEqual(result["linked_rows"], 2)
                with db.get_connection() as conn:
                    linked = conn.execute("SELECT linked_record_id FROM finance_ledger_transactions WHERE import_run_id=?", (run_id,)).fetchall()
                    self.assertIsNotNone(linked[0][0])
                    self.assertEqual(linked[0][0], linked[1][0])
                snapshot = review.read_original_snapshot(service.get_import_run_by_id(run_id))["departments"]["Technology"]
                self.assertEqual((snapshot["auto_linked"], snapshot["unresolved"]), (2, 0))

    def test_manual_promotion_reconciles_related_rows_without_overwriting_review_decisions(self):
        target = self.ledger(po_number="PROMOTE-01", normalized_po_number="PROMOTE")
        related = self.ledger(po_number="PROMOTE-02", normalized_po_number="PROMOTE")
        ignored = self.ledger(po_number="PROMOTE-03", normalized_po_number="PROMOTE")
        workflow.review_action("Technology", ignored, "ignore", 1)
        record_id = workflow.review_action("Technology", target, "create", 1)
        with db.get_connection() as conn:
            rows = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM finance_ledger_transactions")}
            self.assertEqual(rows[target]["linked_record_id"], record_id)
            self.assertEqual(rows[related]["linked_record_id"], record_id)
            self.assertIsNone(rows[ignored]["linked_record_id"])
            self.assertEqual(rows[ignored]["review_status"], "ignored")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_records").fetchone()[0], 1)

    def test_empty_snapshot_and_more_than_sqlite_parameter_limit(self):
        run_id = self.new_run()
        self.import_data([], run_id)
        context = review.get_import_context("Technology", run_id)
        self.assertEqual(review.review_page("Technology", import_context=context)["total"], 0)
        context["original"]["transaction_ids"] = list(range(1, 1201))
        self.assertEqual(review.review_counts("Technology", context)["unresolved"], 0)
        context["original"]["transaction_ids"] = ["1) OR 1=1"]
        with self.assertRaises(ValueError):
            review.review_counts("Technology", context)

    def test_stale_actions_and_failed_creation_are_atomic(self):
        record = self.record(po_number="DUPLICATE")
        ledger_id = self.ledger(po_number="DUPLICATE")
        with db.get_connection() as conn:
            version = conn.execute("SELECT updated_at FROM finance_ledger_transactions WHERE id=?", (ledger_id,)).fetchone()[0]
        with self.assertRaises(ValueError):
            workflow.review_action("Technology", ledger_id, "create", 1, expected_updated_at=version)
        workflow.review_action("Technology", ledger_id, "ignore", 1, expected_updated_at=version)
        with self.assertRaises(ValueError):
            workflow.review_action("Technology", ledger_id, "link", 1, record, expected_updated_at=version)
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_records").fetchone()[0], 1)
            row = conn.execute("SELECT * FROM finance_ledger_transactions WHERE id=?", (ledger_id,)).fetchone()
            self.assertEqual(row["review_status"], "ignored")
            self.assertIsNone(row["linked_record_id"])


class ReviewRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RouteTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = self.fixture.client
        self.path = "/finance/Technology/ledger/review"

    def post(self, ledger_id, action, **extra):
        with db.get_connection() as conn:
            version = conn.execute("SELECT updated_at FROM finance_ledger_transactions WHERE id=?", (ledger_id,)).fetchone()[0]
        return self.client.post(self.path + "?page=2&per_page=10&vendor_q=Adobe",
            data=dict(ledger_id=ledger_id, action=action, csrf_token="test-csrf", row_version=version, **extra),
            headers={"X-Ledger-Review": "1"})

    def test_actions_update_fragments_counts_and_keep_filter_context(self):
        ids = [self.fixture.ledger(source_hash=f"route-{i}", po_number=f"UNLINKED{i}") for i in range(12)]
        record = self.fixture.record(po_number="MANUAL")
        response = self.post(ids[0], "link", record_id=record)
        self.assertEqual(response.status_code, 200)
        query = parse_qs(urlsplit(response.json["url"]).query)
        self.assertEqual((query["page"], query["vendor_q"], query["per_page"]), (["2"], ["Adobe"], ["10"]))
        self.assertIn("Overall: 11 unresolved", response.json["html"])
        response = self.post(ids[1], "ignore")
        self.assertEqual(parse_qs(urlsplit(response.json["url"]).query)["page"], ["1"])
        response = self.post(ids[2], "reviewed")
        self.assertIn("Overall: 9 unresolved", response.json["html"])
        response = self.post(ids[3], "create")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Overall: 8 unresolved", response.json["html"])
        with db.get_connection() as conn:
            linked = conn.execute("SELECT linked_record_id FROM finance_ledger_transactions WHERE id=?", (ids[0],)).fetchone()[0]
            self.assertEqual(linked, record)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finance_record_history WHERE finance_record_id=? AND event_type='ledger_linked'", (record,)).fetchone()[0], 1)
            self.assertIsNone(conn.execute("SELECT linked_record_id FROM finance_ledger_transactions WHERE id=?", (ids[2],)).fetchone()[0])

    def test_permissions_csrf_cross_department_and_old_versions(self):
        ledger_id = self.fixture.ledger()
        self.assertEqual(self.client.post(self.path, data={"ledger_id": ledger_id, "action": "ignore"}).status_code, 400)
        other = self.fixture.record(department_name="Other")
        self.assertEqual(self.post(ledger_id, "link", record_id=other).status_code, 409)
        with patch.object(routes, "can_manage_department", return_value=False):
            self.assertEqual(self.post(ledger_id, "ignore").status_code, 403)
            html = self.client.get(self.path).get_data(as_text=True)
            self.assertNotIn('data-review-action', html)
        response = self.client.post(self.path, data=dict(ledger_id=ledger_id, action="ignore", csrf_token="test-csrf", row_version="stale"), headers={"X-Ledger-Review": "1"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(review.review_counts("Technology")["unresolved"], 1)

    def test_record_api_compatibility_navigation_and_filter_links(self):
        record = self.fixture.record(friendly_name="Real record")
        for i in range(26):
            self.fixture.ledger(source_hash=f"navigation-{i}")
        response = self.client.get("/finance/Technology/records/search?paged=1")
        self.assertEqual(response.json["rows"][0]["id"], record)
        self.assertIsInstance(self.client.get("/finance/Technology/records/search").json, list)
        response = self.client.get(self.path + "?per_page=10&vendor_q=Adobe")
        html = response.get_data(as_text=True)
        self.assertIn('ledger-transaction-table', html)
        self.assertIn('Back to Ledger', html)
        self.assertIn('Page 1 of 3', html)
        self.assertIn('Real record', html)
        self.assertNotIn('name="page"', html)
        ledger = self.client.get("/finance/Technology/ledger").get_data(as_text=True)
        self.assertEqual(ledger.count('Review Unlinked Transactions'), 1)
        self.assertIn('<span data-unresolved-count>26</span>', ledger)
        self.assertLess(ledger.index('Review Unlinked Transactions'), ledger.index('>Import'))

    def test_normal_ledger_actions_permissions_and_filtered_refresh(self):
        endpoint = "/finance/Technology/ledger/record-action"
        record = self.fixture.record()
        ledger_id = self.fixture.ledger()
        with db.get_connection() as conn:
            version = conn.execute("SELECT updated_at FROM finance_ledger_transactions WHERE id=?", (ledger_id,)).fetchone()[0]
        payload = dict(ledger_id=ledger_id, action="link", record_id=record, row_version=version, csrf_token="test-csrf")
        self.assertEqual(self.client.post(endpoint, data={**payload, "csrf_token": "wrong"}).status_code, 400)
        with patch.object(routes, "can_manage_department", return_value=False):
            self.assertEqual(self.client.post(endpoint, data=payload).status_code, 403)
        other = self.fixture.record(department_name="Other")
        self.assertEqual(self.client.post(endpoint, data={**payload, "record_id": other}).status_code, 409)
        self.assertEqual(self.client.post(endpoint, data={**payload, "row_version": "stale"}).status_code, 409)
        self.assertEqual(self.client.post(endpoint, data=payload).status_code, 200)
        self.assertEqual(self.client.post(endpoint, data=payload).status_code, 409)
        response = self.client.get("/finance/Technology/ledger?review_status=unresolved&vendor_q=Adobe&page=5", headers={"X-Ledger-Review": "1"})
        self.assertEqual(response.status_code, 200)
        query = parse_qs(urlsplit(response.json["url"]).query)
        self.assertEqual(query["page"], ["1"])
        self.assertEqual(query["vendor_q"], ["Adobe"])
        self.assertEqual(response.json["unresolved_count"], 0)
        self.assertNotIn('data-review-row=', response.json["html"])

    def test_both_tables_normalize_dates_and_offer_modal_link_and_create(self):
        from apps.finance.blueprint import format_ledger_date
        for raw in ("2026-08-06", "8/6/2026", "08/06/26", "2026-08-06T00:00:00"):
            self.assertEqual(format_ledger_date(raw), "08/06/2026")
        self.assertEqual(format_ledger_date("bad date"), "—")
        self.fixture.ledger(purchase_date="2026-08-06")
        for url in (self.path, "/finance/Technology/ledger"):
            html = self.client.get(url).get_data(as_text=True)
            self.assertIn('08/06/2026', html)
            self.assertIn('data-ledger-open="link"', html)
            self.assertIn('data-ledger-open="create"', html)
            self.assertIn('data-ledger-modal hidden', html)
            self.assertIn('role="dialog"', html)
            self.assertNotIn('<th>Account</th>', html)

    def test_no_script_post_redirect_preserves_filters(self):
        ledger_id = self.fixture.ledger()
        with db.get_connection() as conn:
            version = conn.execute("SELECT updated_at FROM finance_ledger_transactions WHERE id=?", (ledger_id,)).fetchone()[0]
        response = self.client.post(self.path + "?vendor_q=Adobe&per_page=100", data=dict(
            ledger_id=ledger_id, row_version=version, csrf_token="test-csrf", action="reviewed"))
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.location).query)
        self.assertEqual(query["vendor_q"], ["Adobe"])
        self.assertEqual(query["per_page"], ["100"])

    def test_record_modal_and_search_include_all_department_records(self):
        from html.parser import HTMLParser

        class RecordOptions(HTMLParser):
            def __init__(self):
                super().__init__()
                self.inside = False
                self.ids = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "template" and "data-review-initial-records" in attrs:
                    self.inside = True
                if self.inside and tag == "option":
                    self.ids.append(int(attrs["value"]))

            def handle_endtag(self, tag):
                if tag == "template":
                    self.inside = False

        ids = [self.fixture.record(title=f"Searchable {i:03}", po_number=f"FULL-{i}") for i in range(61)]
        self.fixture.record(department_name="Other", title="Private")
        archived = self.fixture.record(title="Archived")
        with db.get_connection() as conn:
            conn.execute("UPDATE finance_records SET status='archived' WHERE id=?", (archived,))
        for url in (self.path, "/finance/Technology/ledger"):
            html = self.client.get(url).get_data(as_text=True)
            parser = RecordOptions()
            parser.feed(html)
            self.assertEqual(parser.ids, ids)
            self.assertNotIn("Load more Records", html)
        response = self.client.get("/finance/Technology/records/search?all=1&q=Searchable")
        self.assertEqual([row["id"] for row in response.json["rows"]], ids)
        self.assertFalse(response.json["has_more"])
        self.assertEqual(self.client.get("/finance/Technology/records/search?all=1&q=Private").json["rows"], [])

    def test_import_summary_renders_original_and_current_results_separately(self):
        run_id = service.create_import_run(import_type="transactions", source_type="erp_audit_trail", stored_filename="fixture.csv")
        rows = [dict(transaction_code="20", po_number=f"SUMMARY-{i}", vendor_name="Summary Vendor",
                     description="Review needed", purchase_date="2026-08-01", expenditure_amount="15") for i in range(2)]
        with patch.object(importer, "read_import_rows", return_value=rows), \
             patch.object(importer, "_mapped_row", side_effect=lambda row, *args: row):
            importer.execute_ledger_import(run_id=run_id, default_department_name="Technology")
        original = review.read_original_snapshot(service.get_import_run_by_id(run_id))
        url = self.path + f"?run_id={run_id}&scope=import&per_page=10"
        html = self.client.get(url).get_data(as_text=True)
        self.assertIn(f"Original results · Import #{run_id}", html)
        self.assertIn("This import: 2 unresolved", html)
        self.assertNotIn(review.SNAPSHOT_MARKER, html)
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM finance_ledger_transactions WHERE import_run_id=? LIMIT 1", (run_id,)).fetchone()
        response = self.client.post(url, data=dict(ledger_id=row["id"], row_version=row["updated_at"],
            csrf_token="test-csrf", action="reviewed"), headers={"X-Ledger-Review": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("This import: 1 unresolved", response.json["html"])
        self.assertIn("1 reviewed / ignored now", response.json["html"])
        self.assertEqual(review.read_original_snapshot(service.get_import_run_by_id(run_id)), original)


if __name__ == "__main__":
    unittest.main()
