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

The U/V wind encoder checks that both components declare matching units when units are present. It does not silently convert between units and does not invent a default unit when metadata is absent; the map manifest then labels the unit as unknown. The speed magnitude is invariant under an orthogonal rotation, but wind direction is not. If cfgrib marks `GRIB_uvRelativeToGrid` as true, metadata explicitly flags the direction as requiring grid-to-earth rotation. If the decoder explicitly marks it false, the metadata records earth-relative components. If the flag is absent or unrecognized, the reference frame remains unknown; the converter does not silently assume that missing metadata means earth-relative. The GRIB inventory also records `uvRelativeToGrid` and `resolutionAndComponentFlags` when available.


## Meteorological unit conversions

The `meteorological_units` helper provides explicit conversions for pressure (Pa, hPa/mbar, kPa), temperature (K, °C), wind speed (m s-1, km h-1, knots), and precipitation depth (mm, m). It accepts scalar or NumPy-array values and preserves missing values. Unknown units and conversions across physical dimensions are rejected. The GRIB wind encoder uses canonical unit aliases when checking U/V compatibility; it still does not silently convert source fields, so their declared source unit remains recorded.


## Display-only unit conversion

The general scalar converter can create a display raster in a requested unit while preserving decoded source values for scientific point queries. Select exactly one variable when requesting a display conversion:

```bash
python -m ecmwf_collector.tools.grib_to_map forecast.grib2 --variable t2m --display-unit degC
python -m ecmwf_collector.tools.grib_to_map forecast.grib2 --variable msl --display-unit hPa
```

The NPZ `values` array remains in the source GRIB unit and is used by point queries. A separate `display_values` array stores the converted display field; PNG colour limits and the map legend use `display_units`. The point-value panel reports the source unit. Unknown units and incompatible dimensions fail rather than being guessed. This option intentionally requires `--variable` so one requested target unit cannot accidentally be applied to a mixed collection of pressure, temperature, precipitation and other fields. The helper covers explicitly documented dimensions/aliases. Accumulated precipitation depth (mm, m) and precipitation depth rates (mm h-1, mm day-1, mm s-1, including common CF exponent spellings such as `mm h**-1` and `mm s^-1`) are separate dimensions and cannot be converted directly into one another. Mass-flux units such as `kg m-2 s-1` are intentionally not equated with water depth rates without an explicit water-equivalent assumption. Common GRIB/CF spellings are recognized for hectopascals/millibars, degrees Celsius, and wind speed (including `m s**-1`, `m s^-1`, and `km h**-1`); Unicode minus and middle-dot separators are normalized. This is alias normalization only: it does not infer a physical dimension from a variable name or reinterpret mass flux as accumulated precipitation.


## Explicit grid-relative wind rotation

The wind converter accepts `--grid-to-earth-angle-deg` only when cfgrib explicitly marks the components as grid-relative. The angle convention is counter-clockwise from true east to the positive grid-x axis. The conversion is `U_e = U_g cos(a) - V_g sin(a)` and `V_n = U_g sin(a) + V_g cos(a)`. The angle must come from a trusted product specification or independently validated GRIB metadata; the converter does not infer it from grid type or projection names. Without the argument, grid-relative wind directions remain flagged as invalid for true-north bearings. The encoded RGB WebP texture retains the original source U/V channels. The wind-speed NPZ stores the derived `wind_direction_from_degrees` array alongside speed; this bearing is earth-relative only after a valid explicit rotation or when the source frame is already earth-relative. The metadata distinguishes the source component frame from the direction calculation frame.


## Wind direction display layer

The wind converter writes a separate `wind_direction` PNG/NPZ layer only when
the U/V reference frame is confirmed earth-relative, or when an explicitly
trusted `--grid-to-earth-angle-deg` rotation has been applied to grid-relative
components. Unknown or unrotated grid-relative components do not publish a
true-north bearing layer; the wind-speed layer remains available.

Direction colours use a cyclic HSV hue wheel (0° and 360° meet) and the map
renderer reprojects sine and cosine components separately before recovering
the bearing with `atan2`. It does not interpolate raw degree values. Calm or
missing directions remain transparent, as do interpolated cells whose
circular resultant is too small to define a stable bearing. Curvilinear grids
use the decoder-provided 2-D geolocation and the same circular-component
interpolation. The viewer labels the legend as meteorological direction FROM
true north, clockwise.
