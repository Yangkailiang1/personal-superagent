import gzip
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase


class StaticAssetTests(SimpleTestCase):
    def test_gzip_negotiation_preserves_content_and_cache_variant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "assets").mkdir()
            content = b'console.log("workbench");' * 20000
            (root / "assets/app.js").write_bytes(content)
            (root / "assets/app.js.gz").write_bytes(gzip.compress(content))
            with patch("personal_superagent.web.dashboard.DIST", root):
                response = self.client.get(
                    "/app/assets/app.js", HTTP_ACCEPT_ENCODING="gzip"
                )
                self.assertEqual(response["Content-Encoding"], "gzip")
                self.assertIn("Accept-Encoding", response["Vary"])
                self.assertEqual(
                    gzip.decompress(b"".join(response.streaming_content)), content
                )
                response = self.client.get(
                    "/app/assets/app.js", HTTP_ACCEPT_ENCODING="gzip;q=0"
                )
                self.assertNotIn("Content-Encoding", response)
                self.assertEqual(b"".join(response.streaming_content), content)

    def test_asset_cannot_expose_outside_files_or_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "assets").mkdir()
            (root / "private").write_text("secret")
            (root / "assets/link.js").symlink_to(root / "private")
            with patch("personal_superagent.web.dashboard.DIST", root):
                self.assertEqual(
                    self.client.get("/app/assets/link.js").status_code, 404
                )
                self.assertEqual(
                    self.client.get("/app/assets/../private").status_code, 404
                )
