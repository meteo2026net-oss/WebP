# GEFS ensemble statistics engine

WebP now includes a numerical statistics layer for **already decoded and aligned**
GEFS member fields:

- gridpoint ensemble mean;
- population standard deviation (spread);
- optional probability of exceeding a numeric threshold;
- per-gridpoint valid-member counts and missing-value handling.

The engine intentionally does not open GRIB files. Before calling it, a future GRIB
reader must verify that members share the same run, valid time, parameter, level,
units and grid geometry. A matching array shape alone is not proof of matching grids.
Cells with fewer than the configured minimum valid members are returned as NaN.

This is a calculation foundation, not yet an end-to-end GEFS GRIB-to-map workflow.
