"""Unit tests for the Windy GFS point forecast adapter."""
import json
import unittest
from unittest.mock import patch

from ecmwf_collector.windy_gfs import WindyForecastError, WindyGFSClient


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class WindyGFSTests(unittest.TestCase):
    def test_request_uses_gfs_and_returns_aligned_values(self):
        payload = {
            "ts": [1794000000000, 1794010800000],
            "units": {"temp-surface": "°C"},
            "temp-surface": [12.5, None],
            "wind_u-surface": [2.0, 3.0],
        }
        client = WindyGFSClient("test-key")
        with patch("ecmwf_collector.windy_gfs.urlopen", return_value=_Response(payload)) as mocked:
            result = client.fetch(33.5, 36.3)
        request = mocked.call_args.args[0]
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["model"], "gfs")
        self.assertEqual(sent["key"], "test-key")
        self.assertEqual(result.values["temp-surface"], (12.5, None))
        self.assertEqual(len(result.rows()), 2)
        self.assertEqual(result.model_name, "NOAA GFS")

    def test_missing_key_is_rejected_before_network(self):
        with patch.dict("os.environ", {"WINDY_POINT_FORECAST_API_KEY": ""}):
            client = WindyGFSClient("")
            with self.assertRaises(WindyForecastError):
                client.fetch(0, 0)

    def test_invalid_coordinates_are_rejected(self):
        client = WindyGFSClient("test-key")
        with self.assertRaises(ValueError):
            client.fetch(91, 0)
        with self.assertRaises(ValueError):
            client.fetch(0, 181)

    def test_misaligned_response_is_rejected(self):
        payload = {"ts": [1794000000000], "temp-surface": [1, 2]}
        client = WindyGFSClient("test-key")
        with patch("ecmwf_collector.windy_gfs.urlopen", return_value=_Response(payload)):
            with self.assertRaises(WindyForecastError):
                client.fetch(0, 0)

    def test_api_error_does_not_leak_key(self):
        from urllib.error import HTTPError
        client = WindyGFSClient("secret-key")
        error = HTTPError("https://api.windy.com", 401, "Unauthorized", {}, None)
        with patch("ecmwf_collector.windy_gfs.urlopen", side_effect=error):
            with self.assertRaises(WindyForecastError) as caught:
                client.fetch(0, 0)
        self.assertNotIn("secret-key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
