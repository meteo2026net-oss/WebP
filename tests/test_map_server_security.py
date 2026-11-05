"""Regression tests for the map server's filesystem exposure boundary."""
from pathlib import Path
import unittest
from unittest.mock import patch

import serve_map

from serve_map import ALLOWED_ROOTS, ROOT, MapOnlyHandler


class MapServerPathBoundaryTests(unittest.TestCase):
    def setUp(self):
        # translate_path only uses module-level resolved roots; constructing the
        # handler without a socket keeps these checks isolated and deterministic.
        self.handler = object.__new__(MapOnlyHandler)

    def test_allows_map_viewer_assets(self):
        result = Path(self.handler.translate_path("/map_viewer/index.html"))
        self.assertEqual(result, ALLOWED_ROOTS[0] / "index.html")

    def test_allows_generated_map_data(self):
        result = Path(self.handler.translate_path("/output/map_data/field.png"))
        self.assertEqual(result, ALLOWED_ROOTS[1] / "field.png")

    def test_denies_repository_root_files(self):
        self.assertEqual(
            Path(self.handler.translate_path("/README.md")),
            ROOT / "__map_file_not_found__",
        )

    def test_denies_parent_directory_traversal_from_viewer(self):
        self.assertEqual(
            Path(self.handler.translate_path("/map_viewer/../../README.md")),
            ROOT / "__map_file_not_found__",
        )

    def test_denies_encoded_parent_directory_traversal(self):
        self.assertEqual(
            Path(self.handler.translate_path("/map_viewer/%2e%2e/%2e%2e/README.md")),
            ROOT / "__map_file_not_found__",
        )

    def test_denies_traversal_from_generated_data_directory(self):
        self.assertEqual(
            Path(self.handler.translate_path("/output/map_data/../../README.md")),
            ROOT / "__map_file_not_found__",
        )

    def test_ignores_query_string_when_resolving_asset_path(self):
        result = Path(self.handler.translate_path("/map_viewer/index.html?next=/README.md"))
        self.assertEqual(result, ALLOWED_ROOTS[0] / "index.html")

    def test_denies_symlink_escape_from_allowed_directory(self):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="security-test-", dir=ALLOWED_ROOTS[0]) as folder:
            link = Path(folder) / "outside-link"
            link.symlink_to(ROOT / "README.md")
            request_path = "/" + link.relative_to(ROOT).as_posix()
            self.assertEqual(
                Path(self.handler.translate_path(request_path)),
                ROOT / "__map_file_not_found__",
            )

    @patch("serve_map.webbrowser.open")
    @patch("serve_map.ThreadingHTTPServer")
    def test_headless_mode_starts_server_without_browser(self, server_factory, browser_open):
        server = server_factory.return_value
        server.serve_forever.side_effect = KeyboardInterrupt

        serve_map.main(open_browser=False)

        server_factory.assert_called_once_with(("127.0.0.1", 8765), MapOnlyHandler)
        server.serve_forever.assert_called_once()
        server.server_close.assert_called_once()
        browser_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
