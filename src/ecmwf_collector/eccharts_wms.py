"""Secure ECMWF ecCharts WMS client.

The service URL is supplied by the account holder/configuration; no endpoint is
assumed. This client retrieves rendered map images and WMS capabilities only.
It does not download raw GRIB data or persist credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


class EcChartsWMSError(RuntimeError):
    """Safe, credential-redacted ecCharts WMS error."""


@dataclass(frozen=True)
class WMSLayer:
    name: str
    title: str
    abstract: str = ""
    crs: tuple[str, ...] = ()
    styles: tuple[str, ...] = ()
    time_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class WMSCapabilities:
    version: str
    title: str
    layers: tuple[WMSLayer, ...]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(node: ET.Element, name: str) -> str:
    child = next((item for item in node if _local(item.tag) == name), None)
    return (child.text or "").strip() if child is not None else ""


def _safe_endpoint(endpoint: str) -> None:
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("WMS endpoint must be an absolute HTTPS URL")
    if parts.username or parts.password:
        raise ValueError("Do not embed credentials in the WMS endpoint URL")


def _with_params(endpoint: str, params: dict[str, str], token: str = "") -> str:
    _safe_endpoint(endpoint)
    parts = urlsplit(endpoint)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    if token:
        query["token"] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def parse_capabilities(xml_data: bytes | str) -> WMSCapabilities:
    """Parse WMS 1.3/1.1 capabilities, including inherited CRS declarations."""
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        raise EcChartsWMSError("استجابة WMS ليست XML صالحاً.") from None
    version = root.attrib.get("version", "")
    service = next((n for n in root if _local(n.tag) == "Service"), None)
    capability = next((n for n in root if _local(n.tag) == "Capability"), None)
    title = _text(service, "Title") if service is not None else ""
    if capability is None:
        raise EcChartsWMSError("ملف WMS لا يحتوي على قسم Capability.")

    root_layer = next((n for n in capability if _local(n.tag) == "Layer"), None)
    found: list[WMSLayer] = []

    def walk(node: ET.Element, inherited_crs: tuple[str, ...] = ()) -> None:
        crs = list(inherited_crs)
        for child in node:
            if _local(child.tag) in {"CRS", "SRS"} and child.text:
                crs.extend(child.text.split())
        own_name = _text(node, "Name")
        if own_name:
            styles = tuple(
                _text(style, "Name")
                for style in node if _local(style.tag) == "Style" and _text(style, "Name")
            )
            times: list[str] = []
            for child in node:
                if _local(child.tag) == "Dimension" and child.attrib.get("name", "").lower() == "time":
                    if child.text:
                        times.extend(x.strip() for x in child.text.split(",") if x.strip())
                if _local(child.tag) == "Extent" and child.attrib.get("name", "").lower() == "time":
                    if child.text:
                        times.extend(x.strip() for x in child.text.split(",") if x.strip())
            found.append(WMSLayer(
                name=own_name, title=_text(node, "Title") or own_name,
                abstract=_text(node, "Abstract"), crs=tuple(dict.fromkeys(crs)),
                styles=styles, time_values=tuple(dict.fromkeys(times)),
            ))
        for child in node:
            if _local(child.tag) == "Layer":
                walk(child, tuple(dict.fromkeys(crs)))

    if root_layer is not None:
        walk(root_layer)
    return WMSCapabilities(version=version, title=title, layers=tuple(found))


class EcChartsWMSClient:
    """Minimal authenticated WMS client. Token is never logged or persisted."""

    def __init__(self, endpoint: str, token: str, *, timeout: float = 45.0,
                 opener=None) -> None:
        _safe_endpoint(endpoint)
        if not token or not token.strip():
            raise ValueError("ecCharts WMS token is required")
        self._endpoint = endpoint
        self._token = token.strip()
        self.timeout = timeout
        self._opener = opener or urlopen

    def _get(self, params: dict[str, str]) -> tuple[bytes, str]:
        url = _with_params(self._endpoint, params, self._token)
        request = Request(url, headers={"Accept": "application/xml,image/png,image/jpeg"})
        try:
            with self._opener(request, timeout=self.timeout) as response:
                return response.read(), response.headers.get("Content-Type", "")
        except HTTPError as exc:
            raise EcChartsWMSError(f"ecCharts WMS أعاد HTTP {exc.code}.") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise EcChartsWMSError(
                f"تعذر الاتصال بخدمة ecCharts WMS ({type(exc).__name__})."
            ) from None

    def get_capabilities(self) -> WMSCapabilities:
        body, _ = self._get({
            "SERVICE": "WMS", "REQUEST": "GetCapabilities", "VERSION": "1.3.0"
        })
        return parse_capabilities(body)

    def get_map(self, *, layers: tuple[str, ...], bbox: tuple[float, float, float, float],
                crs: str = "CRS:84", width: int = 1200, height: int = 800,
                styles: tuple[str, ...] | None = None, image_format: str = "image/png",
                time: str | None = None, version: str = "1.3.0") -> bytes:
        if not layers or any(not item.strip() for item in layers):
            raise ValueError("At least one non-empty WMS layer is required")
        if len(bbox) != 4 or not all(map(lambda x: isinstance(x, (int, float)), bbox)):
            raise ValueError("bbox must contain four numeric coordinates")
        if width < 1 or height < 1 or width > 4096 or height > 4096:
            raise ValueError("WMS image dimensions must be between 1 and 4096")
        if image_format not in {"image/png", "image/jpeg"}:
            raise ValueError("Only PNG and JPEG map images are supported")
        style_list = styles or tuple("" for _ in layers)
        if len(style_list) != len(layers):
            raise ValueError("styles count must match layers count")
        params = {
            "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": version,
            "LAYERS": ",".join(layers), "STYLES": ",".join(style_list),
            "FORMAT": image_format, "TRANSPARENT": "TRUE",
            "WIDTH": str(width), "HEIGHT": str(height),
            "CRS" if version == "1.3.0" else "SRS": crs,
            "BBOX": ",".join(str(value) for value in bbox),
        }
        if time:
            params["TIME"] = time
        body, content_type = self._get(params)
        if not content_type.lower().startswith("image/") or not body:
            # Never surface the response body: WMS exception documents may echo
            # query parameters, including the authentication token.
            raise EcChartsWMSError("الخدمة لم تُرجع صورة خريطة؛ تحقق من الطبقة والوقت والصلاحيات.")
        return body
