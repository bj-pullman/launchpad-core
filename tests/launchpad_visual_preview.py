"""Export self-contained pages for manual visual QA using disposable databases.

Run: python -m unittest discover -s tests -p launchpad_visual_preview.py
HTML previews go to the ignored repository .visual-qa directory.
"""
import re
import unittest
from pathlib import Path

import test_launchpad_workflows as fixtures


class VisualPreview(unittest.TestCase):
    def test_render_previews(self):
        fixture = fixtures.RouteTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        from apps.snipeops import bp as snipeops_bp
        fixture.app.register_blueprint(snipeops_bp)
        fixtures.set_setting("setup.completed", "true")
        with fixture.client.session_transaction() as data:
            data["user_permissions"] = [
                "launchpad.settings.security.view",
                "launchpad.settings.security.manage",
                "launchpad.settings.view",
                "snipeops.home.view",
                "launchpad.settings.snipeops.manage",
                "finance.home.view",
                "user360.home.view",
                "gam.home.view",
            ]
        record_id = fixture.record(friendly_name="Adobe Creative Cloud District License", cost="18500", notes="District license; contact Technology for access.")
        fixture.ledger(po_number="UNLINKED", title="Unmatched license activity")
        output = Path(__file__).resolve().parents[1]/".visual-qa"
        output.mkdir(parents=True, exist_ok=True)
        for name, page, theme, size in [
            ("security-light", "/settings/security", "light", "1440,1000"),
            ("security-dark", "/settings/security", "dark", "1440,1000"),
            ("dashboard-dark", "/", "dark", "1440,1000"),
            ("snipeops-dark", "/snipeops/", "dark", "1440,1000"),
            ("account-dark", "/settings/security", "dark", "1440,1000"),
            ("record-dark", f"/finance/records/{record_id}", "dark", "1440,1000"),
            ("review-dark", "/finance/Technology/ledger/review", "dark", "1440,1000"),
            ("security-mobile", "/settings/security", "dark", "390,900"),
        ]:
            with fixture.client.session_transaction() as data:
                data["theme_preference"] = theme
            response = fixture.client.get(page)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            def stylesheet(match):
                href = match.group(1)
                if not href.startswith("/"):
                    return ""
                response = fixture.client.get(href)
                self.assertEqual(response.status_code,200,href)
                return "<style>" + response.get_data(as_text=True) + "</style>"
            html = re.sub(r'<link\b[^>]*href="([^"]+)"[^>]*>', stylesheet, html)
            # Keep only the inline theme initializer: previews are static artifacts.
            html = re.sub(r'<script\b[^>]*src="[^"]+"[^>]*>\s*</script>', '', html)
            if name == "account-dark":
                html = html.replace("</head>", "<style>.nav-dropdown-account .nav-dropdown-menu{display:block}</style></head>")
            target=output/(name+".html")
            target.write_text(html,encoding="utf-8")
        print("Visual QA artifacts:", output)
