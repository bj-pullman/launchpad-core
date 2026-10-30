"""Loopback-only UI fixture backed entirely by temporary test databases.

Run from the repository: python -m unittest discover -s tests -p ledger_review_preview.py
Stop with Ctrl+C. Never uses the application factory or starts scheduled jobs.
"""
import unittest
from unittest.mock import patch

from flask import request
from werkzeug.serving import make_server

import test_launchpad_workflows as fixtures
from apps.finance import service, ledger_import_service as importer


class LedgerReviewPreview(unittest.TestCase):
    def test_serve(self):
        fixture = fixtures.RouteTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for i in range(56):
            fixture.record(title=f"Source license {i:02}", friendly_name=f"District software {i:02}", po_number=f"RECORD-{i}")
        run_id = service.create_import_run(import_type="transactions", source_type="erp_audit_trail", stored_filename="preview.csv")
        rows = [dict(transaction_code="20", vendor_name="Example Technology Vendor", po_number=f"PREVIEW-{i}",
                     account_code="6100", description=f"District device support and software subscription {i:02}",
                     purchase_date="2026-08-01", expenditure_amount="123.45") for i in range(32)]
        with patch.object(importer, "read_import_rows", return_value=rows), \
             patch.object(importer, "_mapped_row", side_effect=lambda row, *args: row):
            importer.execute_ledger_import(run_id=run_id, default_department_name="Technology")
        with fixture.client.session_transaction() as data:
            data["theme_preference"] = "light"
        cookie = fixture.client.get_cookie("session").value
        application = fixture.app.wsgi_app

        def isolated_session(environ, start_response):
            environ["HTTP_COOKIE"] = "session=" + cookie
            return application(environ, start_response)

        fixture.app.wsgi_app = isolated_session

        @fixture.app.get("/__preview/mobile")
        def mobile():
            return '<iframe title="Mobile Ledger review" style="width:390px;height:850px;border:1px solid #999" src="/finance/Technology/ledger/review?run_id=1&per_page=10"></iframe>'

        @fixture.app.before_request
        def preview_theme():
            if request.args.get("theme") == "dark":
                from flask import session
                session["theme_preference"] = "dark"

        server = make_server("127.0.0.1", 8954, fixture.app)
        print("Disposable preview: http://127.0.0.1:8954/finance/Technology/ledger/review?run_id=1&per_page=10", flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
