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
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Existing map manifest is not valid JSON; refusing to overwrite it: {path}"
            ) from exc
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"Existing map manifest is not valid UTF-8; refusing to overwrite it: {path}"
            ) from exc
        except OSError as exc:
            raise OSError(f"Could not read existing map manifest {path}: {exc}") from exc
        if not isinstance(current, dict) or not isinstance(current.get("layers"), list):
            raise ValueError(
                f"Existing map manifest has an invalid structure; expected an object "
                f"with a layers array: {path}"
            )
        if any(not isinstance(layer, dict) for layer in current["layers"]):
            raise ValueError(
                f"Existing map manifest contains a non-object layer; refusing to overwrite it: {path}"
            )
    else:
        current = {"version": 1, "layers": []}
    layers = current["layers"]

    def identity(product: dict) -> str:
        # A GRIB file may contain multiple groups and ensemble/other slices
        # for the same variable, level, and valid time. Keep those products
        # distinct instead of silently replacing one another in the manifest.
        fields = (
            "source_id", "source_file", "group_index", "variable", "valid_time",
            "typeOfLevel", "level", "step", "extra_coordinates", "units", "display_units",
        )
        return json.dumps(
            [product.get(key) for key in fields],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )

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
