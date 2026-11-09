"""Offline tests for the ecCharts WMS adapter."""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from ecmwf_collector.eccharts_wms import (
    EcChartsWMSError, EcChartsWMSClient, parse_capabilities,
)


CAPABILITIES = b"""<?xml version="1.0"?>
<WMS_Capabilities version="1.3.0" xmlns="http://www.opengis.net/wms">
  <Service><Title>Test ecCharts</Title></Service>
  <Capability><Layer><Title>root</Title><CRS>CRS:84 EPSG:4326</CRS>
    <Layer><Name>temperature</Name><Title>2m Temperature</Title>
      <Style><Name>shaded</Name></Style>
      <Dimension name="time">2026-11-07T00:00:00Z,2026-11-07T06:00:00Z</Dimension>
    </Layer>
  </Layer></Capability>
</WMS_Capabilities>"""


class _Response:
    def __init__(self, body, content_type):
        self.body = body
        self.headers = {"Content-Type": content_type}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.body


class EcChartsWMSTests(unittest.TestCase):
    def test_parse_capabilities_inherits_crs_and_reads_time(self):
        result = parse_capabilities(CAPABILITIES)
        self.assertEqual(result.title, "Test ecCharts")
        self.assertEqual(result.layers[0].name, "temperature")
        self.assertIn("EPSG:4326", result.layers[0].crs)
        self.assertEqual(result.layers[0].styles, ("shaded",))
        self.assertEqual(len(result.layers[0].time_values), 2)

    def test_capabilities_request_contains_auth_token_without_logging_it(self):
        captured = {}
        def opener(request, timeout):
            captured["url"] = request.full_url
            return _Response(CAPABILITIES, "application/xml")
        client = EcChartsWMSClient("https://example.test/wms", "private-token", opener=opener)
        result = client.get_capabilities()
        self.assertEqual(result.layers[0].name, "temperature")
        query = parse_qs(urlsplit(captured["url"]).query)
        self.assertEqual(query["REQUEST"], ["GetCapabilities"])
        self.assertEqual(query["token"], ["private-token"])

    def test_get_map_builds_expected_wms_parameters(self):
        captured = {}
        def opener(request, timeout):
            captured["url"] = request.full_url
            return _Response(b"PNGDATA", "image/png")
        client = EcChartsWMSClient("https://example.test/wms", "secret", opener=opener)
        data = client.get_map(layers=("temperature",), bbox=(-10, 20, 30, 60),
                              time="2026-11-07T00:00:00Z")
        self.assertEqual(data, b"PNGDATA")
        query = parse_qs(urlsplit(captured["url"]).query)
        self.assertEqual(query["REQUEST"], ["GetMap"])
        self.assertEqual(query["LAYERS"], ["temperature"])
        self.assertEqual(query["TIME"], ["2026-11-07T00:00:00Z"])
        self.assertEqual(query["CRS"], ["CRS:84"])

    def test_non_image_response_is_rejected_without_echoing_body(self):
        client = EcChartsWMSClient(
            "https://example.test/wms", "private-token",
            opener=lambda request, timeout: _Response(
                b"<ServiceException>private-token denied</ServiceException>", "application/xml"
            ),
        )
        with self.assertRaises(EcChartsWMSError) as caught:
            client.get_map(layers=("missing",), bbox=(-10, 20, 30, 60))
        self.assertNotIn("private-token", str(caught.exception))

    def test_rejects_http_endpoint_and_invalid_dimensions(self):
        with self.assertRaises(ValueError):
            EcChartsWMSClient("http://example.test/wms", "token")
        client = EcChartsWMSClient("https://example.test/wms", "token")
        with self.assertRaises(ValueError):
            client.get_map(layers=("x",), bbox=(0, 0, 1, 1), width=5000)


if __name__ == "__main__":
    unittest.main()
