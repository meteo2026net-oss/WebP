#!/usr/bin/env python3
"""Serve the local map viewer, map assets, and safe point-value query endpoint."""
from __future__ import annotations

import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from ecmwf_collector.tools.point_query import sample_npz  # noqa: E402

MAP_DATA = (ROOT / "output" / "map_data").resolve()
ALLOWED_ROOTS = ((ROOT / "map_viewer").resolve(), MAP_DATA)


class MapOnlyHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def translate_path(self, path: str) -> str:
        relative = unquote(urlsplit(path).path).lstrip("/")
        candidate = (ROOT / relative).resolve()
        if any(candidate == allowed or allowed in candidate.parents for allowed in ALLOWED_ROOTS):
            return str(candidate)
        return str(ROOT / "__map_file_not_found__")

    def _json_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _point_query(self, query: dict) -> None:
        try:
            image_name = query.get("image", [""])[0]
            latitude = float(query.get("lat", [""])[0])
            longitude = float(query.get("lon", [""])[0])
            if not image_name or Path(image_name).name != image_name:
                raise ValueError("Invalid layer selection.")
            manifest_path = MAP_DATA / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry = next((x for x in manifest.get("layers", []) if x.get("image") == image_name), None)
            if entry is None:
                self._json_response(404, {"error": "Layer not found in manifest."})
                return
            data_name = entry.get("data_file")
            if not data_name or Path(data_name).name != data_name or not data_name.endswith(".npz"):
                self._json_response(404, {"error": "This layer has no point-query data."})
                return
            data_path = (MAP_DATA / data_name).resolve()
            if data_path.parent != MAP_DATA or not data_path.is_file():
                self._json_response(404, {"error": "Scientific data file is unavailable."})
                return
            result = sample_npz(data_path, latitude, longitude)
            result.update({
                "variable": entry.get("variable"),
                "long_name": entry.get("long_name"),
                "units": entry.get("units"),
                "valid_time": entry.get("valid_time"),
                "requested_latitude": latitude,
                "requested_longitude": longitude,
            })
            self._json_response(200, result)
        except (ValueError, TypeError, OSError, KeyError, json.JSONDecodeError) as exc:
            self._json_response(400, {"error": str(exc)})

    def do_GET(self):
        parsed = urlsplit(self.path)
        requested = parsed.path
        if requested == "/api/point":
            self._point_query(parse_qs(parsed.query))
            return
        if requested == "/":
            self.send_response(302)
            self.send_header("Location", "/map_viewer/")
            self.end_headers()
            return
        if not (requested.startswith("/map_viewer/") or requested.startswith("/output/map_data/")):
            self.send_error(404, "Only map viewer assets, generated map data, and point queries are served.")
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
    print("Local server exposes map assets and point sampling only. Press Ctrl+C to stop.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping map server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
