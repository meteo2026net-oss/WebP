import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import serve_map


class BundledMapPathTests(unittest.TestCase):
    def test_static_viewer_is_resolved_from_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            viewer = root / "map_viewer"
            viewer.mkdir()
            (viewer / "index.html").write_text("viewer", encoding="utf-8")
            with patch.object(serve_map, "BUNDLE_ROOT", root), patch.object(
                serve_map, "ROOT", root
            ), patch.object(serve_map, "MAP_VIEWER", viewer), patch.object(
                serve_map, "MAP_DATA", root / "user-data" / "output" / "map_data"
            ), patch.object(serve_map, "ALLOWED_ROOTS", (viewer, root / "user-data" / "output" / "map_data")):
                handler = object.__new__(serve_map.MapOnlyHandler)
                self.assertEqual(
                    Path(handler.translate_path("/map_viewer/index.html")),
                    viewer / "index.html",
                )

    def test_generated_map_data_is_resolved_from_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            viewer = root / "bundle" / "map_viewer"
            data = root / "user-data" / "output" / "map_data"
            viewer.mkdir(parents=True)
            data.mkdir(parents=True)
            (data / "layer.png").write_bytes(b"png")
            with patch.object(serve_map, "BUNDLE_ROOT", root / "bundle"), patch.object(
                serve_map, "ROOT", root / "bundle"
            ), patch.object(serve_map, "MAP_VIEWER", viewer), patch.object(
                serve_map, "MAP_DATA", data
            ), patch.object(serve_map, "ALLOWED_ROOTS", (viewer, data)):
                handler = object.__new__(serve_map.MapOnlyHandler)
                self.assertEqual(
                    Path(handler.translate_path("/output/map_data/layer.png")),
                    data / "layer.png",
                )

    def test_server_starts_when_frozen_stdout_is_unavailable(self):
        class FakeServer:
            def __init__(self, address, handler):
                self.address = address
                self.handler = handler
                self.closed = False
            def serve_forever(self):
                return None
            def server_close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as temp:
            logger = serve_map.logging.getLogger("ecmwf_webp.map_server")
            old_handlers = list(logger.handlers)
            for handler in old_handlers:
                logger.removeHandler(handler)
            try:
                with patch.object(serve_map, "project_root", return_value=Path(temp)), patch.object(
                    serve_map, "ThreadingHTTPServer", FakeServer
                ), patch.object(serve_map.sys, "stdout", None):
                    serve_map.main(open_browser=False)
                self.assertTrue((Path(temp) / "logs" / "map_server.log").is_file())
            finally:
                for handler in list(logger.handlers):
                    handler.close()
                    logger.removeHandler(handler)
                for handler in old_handlers:
                    logger.addHandler(handler)

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            viewer = root / "map_viewer"
            data = root / "data"
            viewer.mkdir()
            data.mkdir()
            with patch.object(serve_map, "BUNDLE_ROOT", root), patch.object(
                serve_map, "ROOT", root
            ), patch.object(serve_map, "MAP_VIEWER", viewer), patch.object(
                serve_map, "MAP_DATA", data
            ), patch.object(serve_map, "ALLOWED_ROOTS", (viewer, data)):
                handler = object.__new__(serve_map.MapOnlyHandler)
                result = Path(handler.translate_path("/output/map_data/../../secret.txt"))
                self.assertNotEqual(result, root / "secret.txt")
                self.assertEqual(result, root / "__map_file_not_found__")


if __name__ == "__main__":
    unittest.main()
