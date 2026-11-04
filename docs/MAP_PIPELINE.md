# GRIB-to-map workflow

## Current supported path
1. Download original ECMWF GRIB files with the desktop collector.
2. Inspect the file and identify its fields:
   `python -m ecmwf_collector.tools.inspect_grib path/to/file.grib2 --output output/inventory.json`
3. Convert compatible scalar fields:
   `python -m ecmwf_collector.tools.grib_to_map path/to/file.grib2 --output-dir output/map_data`
4. Open the map viewer from the repository root:
   `python serve_map.py`
   Then browse to `http://127.0.0.1:8765/map_viewer/`.

## Map format
The converter writes transparent RGBA PNG overlays and JSON sidecars containing field name, units, valid time, data range, grid dimensions, and geographic bounds. The viewer uses Leaflet image overlays over OpenStreetMap tiles.

## Grid limitations
The initial renderer supports regular 1-D latitude/longitude grids. Rotated-pole, Lambert, polar stereographic, curvilinear, and other projected grids must be reprojected before rendering. The converter refuses incompatible coordinate shapes instead of silently placing them incorrectly.

## Scientific integrity
PNG is a display product, not the scientific source. Preserve original GRIB files and use their decoded values for calculations. The existing RGB WebP wind texture is an 8-bit quantized encoding and is separate from the display PNG.
