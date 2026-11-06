"""Windy Point Forecast adapter for the global US GFS model.

This adapter returns point forecasts in memory only. It deliberately does not
cache, archive, or redistribute Windy responses.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


WINDY_POINT_FORECAST_URL = "https://api.windy.com/api/point-forecast/v2"
GFS_PARAMETERS = (
    "temp", "dewpoint", "precip", "convPrecip", "snowPrecip", "wind",
    "windGust", "cape", "ptype", "lclouds", "mclouds", "hclouds",
    "rh", "gh", "pressure",
)
GFS_LEVELS = ("surface", "850h", "700h", "500h", "300h")


class WindyForecastError(RuntimeError):
    """Raised when Windy rejects a request or returns an invalid response."""


@dataclass(frozen=True)
class WindyGFSPointForecast:
    latitude: float
    longitude: float
    model: str
    timestamps_ms: tuple[int, ...]
    units: dict[str, str]
    values: dict[str, tuple[float | int | None, ...]]
    provider: str = "Windy API"
    model_name: str = "NOAA GFS"

    def rows(self) -> list[dict[str, Any]]:
        """Return aligned in-memory rows; callers must not persist Windy data."""
        result: list[dict[str, Any]] = []
        for index, timestamp in enumerate(self.timestamps_ms):
            row: dict[str, Any] = {
                "time": datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc),
            }
            for name, series in self.values.items():
                row[name] = series[index] if index < len(series) else None
            result.append(row)
        return result


class WindyGFSClient:
    """Fetch point forecasts from Windy's GFS endpoint.

    Supply the API key directly or through WINDY_POINT_FORECAST_API_KEY.
    The key is never written to disk or included in exception messages.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 30.0,
        endpoint: str = WINDY_POINT_FORECAST_URL,
    ) -> None:
        self._api_key = (api_key or os.environ.get("WINDY_POINT_FORECAST_API_KEY", "")).strip()
        self.timeout = timeout
        self.endpoint = endpoint

    def fetch(
        self,
        latitude: float,
        longitude: float,
        *,
        parameters: tuple[str, ...] = GFS_PARAMETERS,
        levels: tuple[str, ...] = GFS_LEVELS,
    ) -> WindyGFSPointForecast:
        if not self._api_key:
            raise WindyForecastError(
                "لم يتم ضبط مفتاح Windy Point Forecast API. "
                "أضف WINDY_POINT_FORECAST_API_KEY إلى بيئة التشغيل."
            )
        if not -90 <= float(latitude) <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= float(longitude) <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if not parameters or not levels:
            raise ValueError("parameters and levels must not be empty")

        payload = {
            "lat": float(latitude),
            "lon": float(longitude),
            "model": "gfs",
            "parameters": list(parameters),
            "levels": list(levels),
            "key": self._api_key,
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                body = response.read()
        except HTTPError as exc:
            # Do not include response body or request headers: they may contain secrets.
            raise WindyForecastError(f"Windy API returned HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise WindyForecastError(f"تعذر الاتصال بخدمة Windy: {type(exc).__name__}") from None

        if status == 204:
            raise WindyForecastError("Windy لم يُرجع بيانات للمعاملات المطلوبة في هذا الموقع.")
        if status != 200:
            raise WindyForecastError(f"Windy API returned HTTP {status}")

        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise WindyForecastError("Windy أعاد استجابة غير صالحة بصيغة JSON.") from None

        if not isinstance(document, dict) or not isinstance(document.get("ts"), list):
            raise WindyForecastError("استجابة Windy لا تحتوي على سلسلة التوقيت ts.")

        timestamps = tuple(int(value) for value in document["ts"])
        units_raw = document.get("units") or {}
        units = {str(key): str(value) for key, value in units_raw.items()}
        values: dict[str, tuple[float | int | None, ...]] = {}
        for key, series in document.items():
            if key in {"ts", "units"} or not isinstance(series, list):
                continue
            if len(series) != len(timestamps):
                raise WindyForecastError(f"طول السلسلة {key} لا يطابق عدد التوقيتات.")
            values[str(key)] = tuple(series)

        return WindyGFSPointForecast(
            latitude=float(latitude),
            longitude=float(longitude),
            model="gfs",
            timestamps_ms=timestamps,
            units=units,
            values=values,
        )
