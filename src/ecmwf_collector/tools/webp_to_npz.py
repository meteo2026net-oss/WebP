#!/usr/bin/env python3
"""Decode this repository's RGB WebP wind texture into scientific NumPy arrays."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def decode_component(channel: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    if not vmin < vmax:
        raise ValueError("vmin must be smaller than vmax")
    return vmin + (channel.astype(np.float32) / 255.0) * (vmax - vmin)


def decode_texture(image_path: Path, metadata_path: Path | None = None):
    image_path = Path(image_path)
    metadata_path = metadata_path or image_path.with_suffix(".json")
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))

    if metadata.get("encoding_version") != 1:
        raise ValueError("Unsupported or missing encoding_version")
    decode = metadata.get("decode", {})
    vmin, vmax = float(decode["vmin"]), float(decode["vmax"])
    if not vmin < vmax:
        raise ValueError("Invalid decoding range in metadata")

    with Image.open(image_path) as source:
        if source.mode != "RGB":
            raise ValueError(f"Expected RGB WebP texture, got mode {source.mode}")
        rgb = np.asarray(source, dtype=np.uint8)

    grid = metadata.get("grid", {})
    expected = (int(grid.get("height", -1)), int(grid.get("width", -1)))
    if rgb.shape[:2] != expected:
        raise ValueError(f"Image dimensions {rgb.shape[1]}x{rgb.shape[0]} do not match metadata {expected[1]}x{expected[0]}")

    mask = rgb[..., 2] == 255
    if not np.all((rgb[..., 2] == 0) | mask):
        raise ValueError("Validity channel must contain only 0 or 255")

    u = decode_component(rgb[..., 0], vmin, vmax)
    v = decode_component(rgb[..., 1], vmin, vmax)
    u[~mask] = np.nan
    v[~mask] = np.nan
    return u, v, mask, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Decode an RGB WebP wind texture to a compressed NPZ file.")
    parser.add_argument("input_webp", type=Path)
    parser.add_argument("--metadata", type=Path, help="JSON sidecar (defaults to same basename)")
    parser.add_argument("--output", type=Path, default=Path("output/wind_decoded.npz"))
    args = parser.parse_args()

    u, v, valid, metadata = decode_texture(args.input_webp, args.metadata)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, u=u, v=v, valid=valid)
    print(f"Decoded arrays: {args.output}")
    print(f"Shape: {u.shape}; valid cells: {int(valid.sum())}; missing cells: {int((~valid).sum())}")
    print("Note: decoded values retain the source encoder's 8-bit quantization.")


if __name__ == "__main__":
    main()
