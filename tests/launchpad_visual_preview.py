"""Export self-contained pages for manual visual QA using disposable databases.

Run: python -m unittest discover -s tests -p launchpad_visual_preview.py
HTML previews go to a fresh instance/qa subdirectory. This does not verify layout.
"""
import re
import tempfile
import unittest
from pathlib import Path

import test_launchpad_workflows as fixtures


class VisualPreview(unittest.TestCase):
    def test_render_previews(self):
        fixture = fixtures.RouteTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        record_id = fixture.record(friendly_name="Adobe Creative Cloud District License", cost="18500", notes="District license; contact Technology for access.")
        fixture.ledger(po_number="UNLINKED", title="Unmatched license activity")
        artifact_root = Path(__file__).resolve().parents[1]/"instance"/"qa"
        artifact_root.mkdir(parents=True,exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="launchpad-visual-",dir=artifact_root))
        for name, page, theme, size in [
            ("security-light", "/settings/security", "light", "1440,1000"),
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
            target=output/(name+".html")
            target.write_text(html,encoding="utf-8")
        print("Visual QA artifacts:", output)
