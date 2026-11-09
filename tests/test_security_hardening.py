from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from ecmwf_collector.logging_setup import clear_secrets, redact
from ecmwf_collector.secrets_store import SecretStore
from scripts.verify_package_secrets import scan_package


class SecretStoreBackendTests(unittest.TestCase):
    def tearDown(self):
        clear_secrets()

    def _keyring_module(self, backend):
        module = ModuleType("keyring")
        module.get_keyring = lambda: backend
        module.get_password = lambda *args: None
        module.set_password = lambda *args: None
        module.delete_password = lambda *args: None
        return module

    def test_os_credential_vault_backend_is_accepted(self):
        backend_type = type(
            "WinVaultKeyring", (),
            {"__module__": "keyring.backends.Windows", "priority": 5},
        )
        with patch.dict(sys.modules, {"keyring": self._keyring_module(backend_type())}):
            self.assertTrue(SecretStore().available)

    def test_plaintext_or_unknown_keyring_backend_is_rejected(self):
        backend_type = type(
            "PlaintextKeyring", (),
            {"__module__": "keyrings.alt.file", "priority": 1},
        )
        with patch.dict(sys.modules, {"keyring": self._keyring_module(backend_type())}):
            self.assertFalse(SecretStore().available)

    def test_injected_test_adapter_remains_available(self):
        adapter = object()
        self.assertTrue(SecretStore(backend=adapter).available)


class PackageSecretScanTests(unittest.TestCase):
    def test_clean_package_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.txt").write_text("portable app", encoding="utf-8")
            self.assertEqual(scan_package(root), [])

    def test_user_database_profile_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "database-profiles.json").write_text("[]", encoding="utf-8")
            self.assertTrue(any("credential/state file" in item for item in scan_package(root)))

    def test_password_bearing_database_dsn_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.txt").write_text(
                "postgresql://app:secret-value@db.example/weather", encoding="utf-8"
            )
            self.assertTrue(any("DSN containing a password" in item for item in scan_package(root)))

    def test_private_key_material_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "material.bin").write_bytes(b"-----BEGIN PRIVATE KEY-----")
            self.assertTrue(any("private key material" in item for item in scan_package(root)))


class PostgresTlsCaTests(unittest.TestCase):
    def test_connection_probe_passes_explicit_ca_to_libpq(self):
        from ecmwf_collector.connection_profiles import DatabaseProfile, test_database_connection

        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, statement):
                self.statement = statement

        captured = {}
        driver = ModuleType("psycopg")
        driver.connect = lambda **kwargs: (captured.update(kwargs) or FakeConnection())

        class FakeSecrets:
            def get_password(self, key):
                return "vault-password"

        with tempfile.TemporaryDirectory() as directory:
            ca_file = Path(directory) / "root-ca.pem"
            ca_file.write_text("test certificate", encoding="utf-8")
            profile = DatabaseProfile.create(
                "Verified PostgreSQL", "postgresql", host="db.example",
                port=5432, database="weather", username="app",
                ssl_mode="verify-full", ssl_ca=str(ca_file),
            )
            with patch.dict(sys.modules, {"psycopg": driver}):
                ok, message = test_database_connection(profile, FakeSecrets())
        self.assertTrue(ok, message)
        self.assertEqual(captured["sslmode"], "verify-full")
        self.assertEqual(captured["sslrootcert"], str(ca_file))


class StartupDsnRedactionTests(unittest.TestCase):
    def tearDown(self):
        clear_secrets()

    def test_environment_dsn_is_registered_before_connection_attempt(self):
        from main import _select_postgres_dsn

        dsn = "postgresql://app:very-secret-value@db.example/weather"
        selected = _select_postgres_dsn(
            secrets=None, environ={"ECMWF_POSTGRES_DSN": dsn}
        )
        self.assertEqual(selected, dsn)
        self.assertNotIn("very-secret-value", redact(f"connection failed: {dsn}"))
        self.assertIn("********", redact(f"connection failed: {dsn}"))


if __name__ == "__main__":
    unittest.main()
