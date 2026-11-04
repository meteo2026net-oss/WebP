# RGB WebP encoding specification

Each pixel represents one grid cell.

| Channel | Meaning | Decode |
|---|---|---|
| R | U wind component | `vmin + (R / 255) * (vmax - vmin)` |
| G | V wind component | `vmin + (G / 255) * (vmax - vmin)` |
| B | Validity mask | 0 = missing/invalid, 255 = valid |

The default component range is -100 to +100 m/s. It is configurable with
`--vmin` and `--vmax`; the JSON sidecar is the authoritative calibration.

Quantization interval = `(vmax - vmin) / 255`. Values outside the range are
clipped. WebP is saved losslessly, preserving the encoded channel bytes. This
does not preserve original floating-point precision.

The JSON sidecar records grid dimensions, first/last coordinates, coordinate
direction, variable names, units, validity counts, and decoding parameters.

The current encoder accepts only 1-D latitude/longitude coordinates. Verify
grid projection, longitude convention, and image row orientation before map use.
