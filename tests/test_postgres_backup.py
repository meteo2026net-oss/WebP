import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecmwf_collector import postgres_backup


class PostgresBackupTests(unittest.TestCase):

    def test_postgres_client_tools_must_have_matching_major_versions(self):
        with patch.object(postgres_backup, "_tool_major_version", side_effect=[17, 16]):
            with self.assertRaisesRegex(RuntimeError, "same PostgreSQL major version"):
                postgres_backup._validate_tool_pair("pg_dump.exe", "pg_restore.exe")

    def test_postgres_tool_version_is_parsed_from_official_output(self):
        result = type("Result", (), {
            "returncode": 0, "stdout": "pg_dump (PostgreSQL) 17.4", "stderr": ""
        })()
        with patch.object(postgres_backup.subprocess, "run", return_value=result):
            self.assertEqual(postgres_backup._tool_major_version("pg_dump.exe"), 17)

    def test_discovers_tools_from_standard_windows_install_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            bin_dir = Path(temp) / "PostgreSQL" / "17" / "bin"
            bin_dir.mkdir(parents=True)
            executable = bin_dir / "pg_dump.exe"
            executable.write_bytes(b"")
            with patch.dict(os.environ, {"ProgramFiles": temp}, clear=True), \
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
                 patch.object(postgres_backup, "_validate_tool_pair"), \
                 patch.object(postgres_backup.subprocess, "run", side_effect=run):
                backup = postgres_backup.create_postgres_backup(
                    "postgresql://limited:secret@127.0.0.1:5432/weather?sslmode=disable",
                    Path(temp),
                )
            self.assertTrue(backup.is_file())
            self.assertEqual(backup.read_bytes(), b"custom archive")
            metadata = postgres_backup.validate_postgres_backup_manifest(backup)
            self.assertEqual(metadata["database"], "weather")
            self.assertEqual(metadata["size_bytes"], len(b"custom archive"))
            dump_args, dump_kwargs = calls[0]
            self.assertNotIn("secret", " ".join(dump_args))
            self.assertEqual(dump_kwargs["env"]["PGPASSWORD"], "secret")
            self.assertIn("--no-password", dump_args)
            self.assertEqual(calls[1][0][1], "--list")


    def test_restore_refuses_backup_for_different_database_before_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "backup.dump"
            archive.write_bytes(b"archive")
            import hashlib, json
            metadata = {
                "format": "postgresql-custom", "database": "other",
                "size_bytes": 7, "sha256": hashlib.sha256(b"archive").hexdigest(),
            }
            archive.with_suffix(".dump.json").write_text(json.dumps(metadata), encoding="utf-8")
            with patch.object(postgres_backup, "_assert_postgres_restore_access") as access, \\
                 patch.object(postgres_backup, "create_postgres_backup") as safety:
                with self.assertRaisesRegex(ValueError, "does not match"):
                    postgres_backup.restore_postgres_backup(
                        "postgresql://admin@localhost/weather", archive, Path(temp)
                    )
            access.assert_not_called()
            safety.assert_not_called()

    def test_restore_creates_safety_backup_and_uses_single_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "backup.dump"
            archive.write_bytes(b"archive")
            import hashlib, json
            metadata = {
                "format": "postgresql-custom", "database": "weather",
                "size_bytes": 7, "sha256": hashlib.sha256(b"archive").hexdigest(),
            }
            archive.with_suffix(".dump.json").write_text(json.dumps(metadata), encoding="utf-8")
            safety = Path(temp) / "safety.dump"
            calls = []
            def fake_run(args, **kwargs):
                calls.append(args)
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            with patch.object(postgres_backup, "_assert_postgres_restore_access", return_value="weather"), \\
                 patch.object(postgres_backup, "_tool", side_effect=["pg_restore", "pg_dump"]), \\
                 patch.object(postgres_backup, "_validate_tool_pair"), \\
                 patch.object(postgres_backup, "_command_options", return_value=(["--dbname", "dbname=weather"], {})), \\
                 patch.object(postgres_backup.subprocess, "run", side_effect=fake_run), \\
                 patch.object(postgres_backup, "create_postgres_backup", return_value=safety), \\
                 patch("psycopg.connect") as connect:
                connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (
                    "public.files", True, True
                )
                result = postgres_backup.restore_postgres_backup(
                    "postgresql://admin@localhost/weather", archive, Path(temp)
                )
            self.assertEqual(result, safety)
            self.assertEqual(len(calls), 2)
            restore_args = calls[-1]
            self.assertIn("--single-transaction", restore_args)
            self.assertIn("--clean", restore_args)
            self.assertIn("--if-exists", restore_args)
            self.assertIn("--no-owner", restore_args)

    def test_manifest_detects_archive_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "backup.dump"
            archive.write_bytes(b"original archive")
            import hashlib
            import json
            manifest = {
                "format": "postgresql-custom",
                "database": "weather",
                "size_bytes": archive.stat().st_size,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            }
            archive.with_suffix(".dump.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(
                postgres_backup.validate_postgres_backup_manifest(archive)["database"],
                "weather",
            )
            archive.write_bytes(b"modified archive")
            with self.assertRaisesRegex(ValueError, "checksum"):
                postgres_backup.validate_postgres_backup_manifest(archive)


    def test_manifest_rejects_non_object_json(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "backup.dump"
            archive.write_bytes(b"archive")
            archive.with_suffix(".dump.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                postgres_backup.validate_postgres_backup_manifest(archive)

    def test_manifest_rejects_invalid_metadata_fields(self):
        import json
        cases = [
            {"format": "postgresql-custom", "database": "weather", "size_bytes": True, "sha256": "0" * 64},
            {"format": "postgresql-custom", "database": "weather", "size_bytes": 7, "sha256": "bad"},
            {"format": "postgresql-custom", "database": "", "size_bytes": 7, "sha256": "0" * 64},
        ]
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "backup.dump"
            archive.write_bytes(b"archive")
            for metadata in cases:
                archive.with_suffix(".dump.json").write_text(json.dumps(metadata), encoding="utf-8")
                with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                    postgres_backup.validate_postgres_backup_manifest(archive)

    def test_manifest_write_failure_does_not_publish_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            def run(args, **kwargs):
                if "--format=custom" in args:
                    Path(args[args.index("--file") + 1]).write_bytes(b"valid archive")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            with patch.object(postgres_backup, "_tool", side_effect=["pg_dump", "pg_restore"]), \
                 patch.object(postgres_backup, "_validate_tool_pair"), \
                 patch.object(postgres_backup.subprocess, "run", side_effect=run), \
                 patch.object(Path, "write_text", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    postgres_backup.create_postgres_backup(
                        "postgresql://app@localhost/weather", Path(temp)
                    )
            self.assertEqual(list(Path(temp).glob("*.dump")), [])
            self.assertEqual(list(Path(temp).glob("*.json")), [])

    def test_failed_dump_leaves_no_final_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            def fail(args, **kwargs):
                Path(args[args.index("--file") + 1]).write_bytes(b"partial")
                return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "connection failed"})()
            with patch.object(postgres_backup, "_tool", side_effect=["pg_dump", "pg_restore"]), \
                 patch.object(postgres_backup, "_validate_tool_pair"), \
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
                 patch.object(postgres_backup, "_validate_tool_pair"), \
                 patch.object(postgres_backup.subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(RuntimeError, "validation"):
                    postgres_backup.create_postgres_backup(
                        "postgresql://app@localhost/weather", Path(temp)
                    )
            self.assertEqual(list(Path(temp).glob("*.dump")), [])

    def test_rotation_keeps_requested_number(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(postgres_backup, "_tool", side_effect=["pg_dump", "pg_restore"] * 3), \
                 patch.object(postgres_backup, "_validate_tool_pair"), \
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
