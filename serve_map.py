#!/usr/bin/env python3
"""Serve only the interactive map assets and generated map layers on localhost."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parent
ALLOWED_ROOTS = ((ROOT / "map_viewer").resolve(), (ROOT / "output" / "map_data").resolve())


class MapOnlyHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def translate_path(self, path: str) -> str:
        relative = unquote(urlsplit(path).path).lstrip("/")
        candidate = (ROOT / relative).resolve()
        if any(candidate == allowed or allowed in candidate.parents for allowed in ALLOWED_ROOTS):
            return str(candidate)
        return str(ROOT / "__map_file_not_found__")

    def do_GET(self):
        requested = urlsplit(self.path).path
        if requested == "/":
            self.send_response(302)
            self.send_header("Location", "/map_viewer/")
            self.end_headers()
            return
        if not (requested.startswith("/map_viewer/") or requested.startswith("/output/map_data/")):
            self.send_error(404, "Only map viewer assets and generated map data are served.")
            return
        super().do_GET()

    def list_directory(self, path):
        self.send_error(403, "Directory listing is disabled.")
        return None


def main():
    address = ("127.0.0.1", 8765)
    server = ThreadingHTTPServer(address, MapOnlyHandler)
    url = f"http://{address[0]}:{address[1]}/map_viewer/"
    print(f"Map viewer: {url}")
    print("This local server exposes only map_viewer/ and output/map_data/. Press Ctrl+C to stop.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping map server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
