# GRIB-to-map workflow

## Current supported path
1. Download original ECMWF GRIB files with the desktop collector.
2. Inspect the file and identify its fields:
   `python -m ecmwf_collector.tools.inspect_grib path/to/file.grib2 --output output/inventory.json`
3. Convert compatible scalar fields and split their forecast-time/vertical-level dimensions into individual map layers:
   `python -m ecmwf_collector.tools.grib_to_map path/to/file.grib2 --output-dir output/map_data`
4. Open the map viewer from the repository root:
   `python serve_map.py`
   Then browse to `http://127.0.0.1:8765/map_viewer/`.

## Map format
The converter writes transparent RGBA PNG overlays and JSON sidecars containing field name, units, valid time, data range, grid dimensions, and geographic bounds. The viewer uses Leaflet image overlays over OpenStreetMap tiles.

## Grid limitations
The initial renderer supports regular 1-D latitude/longitude grids. Non-spatial dimensions such as forecast step and pressure level are sliced into separate products where available. Rotated-pole, Lambert, polar stereographic, curvilinear, and other projected grids must be reprojected before rendering. The converter refuses incompatible coordinate shapes instead of silently placing them incorrectly.

## Scientific integrity
PNG is a display product, not the scientific source. Preserve original GRIB files and use their decoded values for calculations. The existing RGB WebP wind texture is an 8-bit quantized encoding and is separate from the display PNG.


## استخراج القيم عند الإحداثيات

يحفظ محول الحقول العددية شبكة القيم الأصلية والإحداثيات في ملف `.npz` بجوار صورة الطبقة، ويضيف اسم الملف إلى `manifest.json`. تحفظ هذه الملفات القيم العددية قبل تلوينها، ولا يُستخدم لون الصورة لتقدير القيمة.

عند النقر على الخريطة يرسل العارض الإحداثيات إلى نقطة النهاية المحلية:

```text
GET /api/point?image=<layer-image>&lat=<latitude>&lon=<longitude>
```

يتحقق الخادم من أن اسم الصورة موجود في manifest، ثم يقرأ ملف البيانات المرتبط بها ويعيد أقرب خلية شبكية صالحة مع الإحداثيات والقيمة والوحدة ووقت الصلاحية. اختيار أقرب خلية هو الطريقة الحالية؛ الاستيفاء الثنائي بين الخلايا غير مفعّل بعد. يدعم البحث عن أقرب خط طول الالتفاف حول خط التاريخ الدولي.

ملفات NPZ تحفظ بيانات الشبكة بعد فك GRIB إلى float32. احتفظ بملف GRIB الأصلي لأي حسابات تحتاج دقة المصدر الكاملة.


## Forecast timeline

The map viewer groups compatible layers by variable, level, units, and non-time coordinates. If multiple valid times or forecast steps exist, a slider lets the user switch between frames and a play control cycles through them. This is a client-side frame switcher, not a meteorological animation/interpolation engine; each frame is an independently decoded GRIB field.


## Antimeridian and global longitude coverage

Regular one-dimensional longitude grids that cross the international date line are kept in a continuous unwrapped interval (for example 170°E through 190°E). The map bounds are not clipped at ±180°, preventing the raster from being squeezed or losing its eastern/western edge. Full-world cyclic grids likewise retain their complete 360° pixel-edge extent. Point sampling continues to use the original GRIB coordinates and unwraps longitude differences around the date line.


## Point sampling methods

The local point-query endpoint accepts an optional `method` parameter:
- `nearest` (default): returns the nearest source grid cell, preserving the original discrete-grid behaviour.
- `bilinear`: interpolates between the four surrounding cells on a regular 1-D latitude/longitude grid. It refuses extrapolation outside cell centres and returns no numeric value if any required corner is missing.

Example:
`GET /api/point?image=layer.png&lat=32.5&lon=36.5&method=bilinear`

The map viewer exposes this choice next to the point-value panel. Bilinear output is an interpolation of the decoded field, not an additional observation or a higher-resolution forecast.
