import unittest

from ecmwf_collector.tools.inspect_grib import safe_get


class SafeGetTests(unittest.TestCase):
    def test_optional_key_failure_remains_none(self):
        def getter(_gid, _key):
            raise KeyError("optional key is not defined")

        self.assertIsNone(safe_get(object(), "optionalGridKey", getter))

    def test_required_key_failure_reports_ec_codes_exception(self):
        def getter(_gid, _key):
            raise ValueError("handle is invalid")

        with self.assertRaisesRegex(
            RuntimeError,
            "required GRIB key 'edition'.*ValueError.*handle is invalid",
        ):
            safe_get(object(), "edition", getter)


if __name__ == "__main__":
    unittest.main()
