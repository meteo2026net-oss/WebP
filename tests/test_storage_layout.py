"""Tests for the shared local data-storage layout."""
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.storage_layout import (
    data_root,
    default_wmo_download_root,
    processing_output_dir,
    source_output_dir,
)


class StorageLayoutTests(unittest.TestCase):
    def test_environment_override_is_shared_by_all_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "weather-data"
            env = {"ECMWF_WEBP_DATA_ROOT": str(root)}
            project = Path(tmp) / "project"
            self.assertEqual(data_root(project, env), root)
            self.assertEqual(source_output_dir("ECMWF", project, env), root / "Sources" / "ECMWF")
            self.assertEqual(processing_output_dir(project, env), root / "Processing" / "MapData")

    def test_legacy_wmo_default_moves_to_source_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "archive"
            env = {"ECMWF_WEBP_DATA_ROOT": str(root)}
            self.assertEqual(
                default_wmo_download_root("downloads", Path(tmp), env),
                root / "Sources" / "WMO",
            )

    def test_custom_absolute_and_relative_wmo_paths_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            absolute = Path(tmp) / "custom"
            self.assertEqual(default_wmo_download_root(str(absolute), project), absolute)
            self.assertEqual(
                default_wmo_download_root("my_downloads", project),
                project / "my_downloads",
            )

    def test_unknown_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                source_output_dir("UNKNOWN", Path(tmp), {"ECMWF_WEBP_DATA_ROOT": tmp})


if __name__ == "__main__":
    unittest.main()
