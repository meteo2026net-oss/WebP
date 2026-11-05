import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecmwf_collector import postgres_windows


class PostgreSQLWindowsDiagnosticsTests(unittest.TestCase):
    def test_finds_postgres_binaries_in_standard_windows_install_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            bin_dir = Path(temp) / "PostgreSQL" / "17" / "bin"
            bin_dir.mkdir(parents=True)
            for name in ("postgres", "pg_ctl", "initdb", "pg_dump", "pg_restore"):
                (bin_dir / f"{name}.exe").write_bytes(b"")
            with patch.object(postgres_windows.os, "name", "nt"), \
                 patch.dict(os.environ, {"ProgramFiles": temp}, clear=True), \
                 patch.object(postgres_windows.shutil, "which", return_value=None):
                result = postgres_windows.diagnose_postgres_installation()
            self.assertTrue(result["server_binary_found"])
            self.assertTrue(result["client_tools_found"])
            self.assertEqual(result["tools"]["pg_ctl"], str(bin_dir / "pg_ctl.exe"))
            self.assertTrue(result["read_only"])

    def test_reports_missing_installation_without_mutating_machine(self):
        with patch.object(postgres_windows, "_find_binary", return_value=None), \
             patch.object(postgres_windows, "_windows_services", return_value=[]):
            result = postgres_windows.diagnose_postgres_installation()
        self.assertFalse(result["server_installation_detected"])
        self.assertFalse(result["service_running"])
        self.assertEqual(result["services"], [])

    def test_reports_running_windows_postgres_service(self):
        with patch.object(postgres_windows, "_find_binary", return_value=None), \
             patch.object(postgres_windows, "_windows_services", return_value=[
                 {"name": "postgresql-x64-17", "state": "RUNNING"}
             ]):
            result = postgres_windows.diagnose_postgres_installation()
        self.assertTrue(result["server_installation_detected"])
        self.assertTrue(result["service_running"])


if __name__ == "__main__":
    unittest.main()
