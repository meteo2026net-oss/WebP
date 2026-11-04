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
The renderer supports regular 1-D latitude/longitude grids and 2-D geolocation grids. For 2-D geolocation, it transforms decoder-provided latitude/longitude cell centres to EPSG:3857 and interpolates onto a regular display raster. This makes regional rotated-pole, Lambert, polar-stereographic and other projected GRIB grids renderable when cfgrib exposes matching 2-D latitude/longitude coordinates. It does not guess projection parameters. Curvilinear interpolation currently uses linear triangulation and is limited to regional extents; global/seam-spanning curvilinear grids require a dedicated tiling path. Missing geolocation outside a projected grid's valid domain is masked and ignored rather than invalidating the entire field. Non-spatial dimensions such as forecast step and pressure level are sliced into separate products.

## Scientific integrity
PNG is a display product, not the scientific source. Preserve original GRIB files and use their decoded values for calculations. The existing RGB WebP wind texture is an 8-bit quantized encoding and is separate from the display PNG.


## استخراج القيم عند الإحداثيات

يحفظ محول الحقول العددية شبكة القيم الأصلية والإحداثيات في ملف `.npz` بجوار صورة الطبقة، ويضيف اسم الملف إلى `manifest.json`. تحفظ هذه الملفات القيم العددية قبل تلوينها، ولا يُستخدم لون الصورة لتقدير القيمة.

عند النقر على الخريطة يرسل العارض الإحداثيات إلى نقطة النهاية المحلية:

```text
GET /api/point?image=<layer-image>&lat=<latitude>&lon=<longitude>
```

يتحقق الخادم من أن اسم الصورة موجود في manifest، ثم يقرأ ملف البيانات المرتبط بها. للشبكات المنتظمة ذات إحداثيات 1-D يمكن اختيار أقرب خلية أو الاستيفاء الثنائي. أما الشبكات ذات الإحداثيات الجغرافية 2-D فيُعاد أقرب مركز خلية صالح، مع تجاهل الخلايا التي لا تملك إحداثيات جغرافية صالحة؛ الاستيفاء الثنائي غير متاح لها بعد.

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


## Curvilinear and projected grids

When cfgrib exposes matching two-dimensional `latitude(y, x)` and `longitude(y, x)` coordinates, the converter preserves those arrays and sends the field through a geolocation-based reprojection to EPSG:3857. This supports regional Lambert, polar stereographic and rotated-pole products without inferring projection parameters from incomplete metadata. The renderer uses linear triangulation; cells outside the geolocation convex hull remain transparent. For these 2-D grids, point queries use the nearest geolocated cell. Bilinear sampling remains limited to regular 1-D grids. Global or seam-spanning curvilinear fields are explicitly outside this initial implementation.


## Wind vectors and direction convention

The U/V converter accepts matching regular 1-D latitude/longitude coordinates or matching 2-D decoder-provided geolocation arrays. The two components must share the same spatial dimensions and are aligned with an exact xarray join before encoding.

Wind speed is computed as `sqrt(U² + V²)`. The reported meteorological direction is the direction **from which** the wind blows, in degrees clockwise from true north:
`(degrees(atan2(-U, -V)) + 360) % 360`.
For calm wind (zero speed), direction is undefined and stored as NaN rather than assigning a misleading bearing. Missing U or V produces a missing vector. The RGB WebP texture remains an 8-bit quantized transport/display encoding; preserve original GRIB for scientific calculations.


## Wind component validation and reference frame

The U/V wind encoder checks that both components declare matching units when units are present. It does not silently convert between units and does not invent a default unit when metadata is absent; the map manifest then labels the unit as unknown. The speed magnitude is invariant under an orthogonal rotation, but wind direction is not. If cfgrib marks `GRIB_uvRelativeToGrid` as true, metadata explicitly flags the direction as requiring grid-to-earth rotation. If the decoder does not declare the reference frame, the metadata warns that the bearing must be verified before treating it as a true-north meteorological direction.
