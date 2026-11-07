import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from ecmwf_collector.config import project_root, resource_root


class RuntimePathTests(unittest.TestCase):
    def test_source_mode_uses_repository_root(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(project_root(), Path(__file__).resolve().parents[1])
            self.assertEqual(resource_root(), Path(__file__).resolve().parents[1])

    def test_frozen_mode_uses_user_data_directory(self):
        with patch.object(sys, "frozen", True, create=True), patch.dict(
            os.environ, {"LOCALAPPDATA": "C:/Users/Test/AppData/Local"}
        ):
            self.assertEqual(
                project_root(),
                Path("C:/Users/Test/AppData/Local/ECMWFWebP"),
            )

    def test_frozen_mode_uses_pyinstaller_resource_directory(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "_MEIPASS", "C:/Program Files/ECMWFWebP/_internal", create=True
        ):
            self.assertEqual(
                resource_root(),
                Path("C:/Program Files/ECMWFWebP/_internal"),
            )


if __name__ == "__main__":
    unittest.main()
