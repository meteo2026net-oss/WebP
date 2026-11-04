"""Atomic manifest maintenance for map viewer layers."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path


def update_manifest(output_dir: Path, products: list[dict]) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "manifest.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "layers": []}
    except (OSError, json.JSONDecodeError):
        current = {"version": 1, "layers": []}
    layers = current.get("layers", [])
    identity = lambda p: (p.get("source_id"), p.get("source_file"), p.get("variable"), p.get("valid_time"), p.get("typeOfLevel"), p.get("level"), p.get("step"))
    keys = {identity(p) for p in products}
    layers = [p for p in layers if identity(p) not in keys]
    layers.extend(products)
    payload = {"version": 1, "layers": layers}
    fd, tmp = tempfile.mkstemp(dir=output_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path
