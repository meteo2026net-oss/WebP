import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecmwf_collector import postgres_backup


class PostgresBackupTests(unittest.TestCase):

    def test_discovers_tools_from_standard_windows_install_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            bin_dir = Path(temp) / "PostgreSQL" / "17" / "bin"
            bin_dir.mkdir(parents=True)
            executable = bin_dir / "pg_dump.exe"
            executable.write_bytes(b"")
            with patch.dict(os.environ, {"ProgramFiles": temp}, clear=True), \\
                 patch.object(postgres_backup.shutil, "which", return_value=None):
                self.assertEqual(postgres_backup._tool("pg_dump"), str(executable))

    def test_explicit_tool_override_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "custom-pg_dump.exe"
            executable.write_bytes(b"")
            with patch.object(postgres_backup.shutil, "which", return_value=None):
                self.assertEqual(
                    postgres_backup._tool("pg_dump", str(executable)), str(executable)
                )

    def test_backup_uses_password_environment_not_command_line_and_validates_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []

            def run(args, **kwargs):
                calls.append((args, kwargs))
                if "--format=custom" in args:
                    Path(args[args.index("--file") + 1]).write_bytes(b"custom archive")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch.object(postgres_backup, "_tool", side_effect=["pg_dump.exe", "pg_restore.exe"]), \
                 patch.object(postgres_backup.subprocess, "run", side_effect=run):
                backup = postgres_backup.create_postgres_backup(
                    "postgresql://limited:secret@127.0.0.1:5432/weather?sslmode=disable",
                    Path(temp),
                )
            self.assertTrue(backup.is_file())
            self.assertEqual(backup.read_bytes(), b"custom archive")
            dump_args, dump_kwargs = calls[0]
            self.assertNotIn("secret", " ".join(dump_args))
            self.assertEqual(dump_kwargs["env"]["PGPASSWORD"], "secret")
            self.assertIn("--no-password", dump_args)
            self.assertEqual(calls[1][0][1], "--list")

    def test_failed_dump_leaves_no_final_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            def fail(args, **kwargs):
                Path(args[args.index("--file") + 1]).write_bytes(b"partial")
                return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "connection failed"})()
            with patch.object(postgres_backup, "_tool", side_effect=["pg_dump", "pg_restore"]), \
                 patch.object(postgres_backup.subprocess, "run", side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, "pg_dump failed"):
                    postgres_backup.create_postgres_backup(
                        "postgresql://app:secret@localhost/weather", Path(temp)
                    )
            self.assertEqual(list(Path(temp).glob("*.dump")), [])
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_invalid_archive_is_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            def run(args, **kwargs):
                if "--format=custom" in args:
                    Path(args[args.index("--file") + 1]).write_bytes(b"invalid")
                return type("Result", (), {
                    "returncode": 0 if "--format=custom" in args else 1,
                    "stdout": "", "stderr": "bad archive",
                })()
            with patch.object(postgres_backup, "_tool", side_effect=["pg_dump", "pg_restore"]), \
                 patch.object(postgres_backup.subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(RuntimeError, "validation"):
                    postgres_backup.create_postgres_backup(
                        "postgresql://app@localhost/weather", Path(temp)
                    )
            self.assertEqual(list(Path(temp).glob("*.dump")), [])

    def test_rotation_keeps_requested_number(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(postgres_backup, "_tool", side_effect=["pg_dump", "pg_restore"] * 3), \
                 patch.object(postgres_backup.subprocess, "run") as run:
                def fake(args, **kwargs):
                    if "--format=custom" in args:
                        Path(args[args.index("--file") + 1]).write_bytes(b"archive")
                    return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
                run.side_effect = fake
                for _ in range(3):
                    postgres_backup.create_postgres_backup(
                        "postgresql://app@localhost/weather", Path(temp), keep=2
                    )
            self.assertEqual(len(list(Path(temp).glob("postgres-weather-*.dump"))), 2)


if __name__ == "__main__":
    unittest.main()
