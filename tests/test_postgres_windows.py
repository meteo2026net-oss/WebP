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

    def test_installer_refuses_non_windows(self):
        with patch.object(postgres_windows.os, "name", "posix"):
            with self.assertRaisesRegex(RuntimeError, "Windows"):
                postgres_windows.install_postgres_with_winget()

    def test_installer_uses_interactive_winget_and_never_passes_password(self):
        detected = {
            "server_installation_detected": True,
            "services": [{"name": "postgresql-x64-16", "state": "RUNNING"}],
        }
        with patch.object(postgres_windows.os, "name", "nt"), \
             patch.object(postgres_windows, "diagnose_postgres_installation",
                          side_effect=[{"server_installation_detected": False}, detected]), \
             patch.object(postgres_windows.shutil, "which", return_value="C:/Windows/winget.exe"), \
             patch.object(postgres_windows.subprocess, "run") as run:
            run.return_value = type("Result", (), {
                "returncode": 0, "stdout": "", "stderr": "",
            })()
            result = postgres_windows.install_postgres_with_winget()
        args = run.call_args.args[0]
        self.assertIn("--interactive", args)
        self.assertNotIn("--silent", args)
        self.assertNotIn("--override", args)
        self.assertTrue(result["installed"])
        self.assertEqual(result["diagnostics"], detected)

    def test_installer_does_not_reinstall_existing_server(self):
        detected = {"server_installation_detected": True, "services": []}
        with patch.object(postgres_windows.os, "name", "nt"), \
             patch.object(postgres_windows, "diagnose_postgres_installation", return_value=detected), \
             patch.object(postgres_windows.subprocess, "run") as run:
            result = postgres_windows.install_postgres_with_winget()
        run.assert_not_called()
        self.assertTrue(result["already_present"])

    def test_reports_missing_installation_without_mutating_machine(self):
        with patch.object(postgres_windows, "_find_binary", return_value=None), \
             patch.object(postgres_windows, "_windows_services", return_value=[]):
            result = postgres_windows.diagnose_postgres_installation()
        self.assertFalse(result["server_installation_detected"])
        self.assertFalse(result["service_running"])
        self.assertEqual(result["services"], [])

    def test_parses_windows_postgres_service_state(self):
        listed = type("Result", (), {
            "returncode": 0,
            "stdout": "SERVICE_NAME: postgresql-x64-17\n        DISPLAY_NAME: PostgreSQL Server 17\n",
        })()
        detail = type("Result", (), {
            "returncode": 0,
            "stdout": "SERVICE_NAME: postgresql-x64-17\n        STATE              : 4  RUNNING\n",
        })()
        with patch.object(postgres_windows.os, "name", "nt"), \
             patch.object(postgres_windows.subprocess, "run", side_effect=[listed, detail]):
            services = postgres_windows._windows_services()
        self.assertEqual(
            services, [{"name": "postgresql-x64-17", "state": "RUNNING"}]
        )

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
