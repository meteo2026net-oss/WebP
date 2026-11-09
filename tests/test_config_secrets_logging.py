import json
import logging
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.config import AppConfig, ConfigError, load_config, save_config
from ecmwf_collector.logging_setup import (RedactingFormatter, clear_secrets,
                                           redact, register_secret, setup_logging)
from ecmwf_collector.secrets_store import SecretStore


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        c = AppConfig()
        self.assertEqual((c.host, c.port, c.passive), ("diss.ecmwf.int", 21, True))

    def test_roundtrip_and_no_password_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            save_config(AppConfig(username="wmo_xx"), p)
            raw = json.loads(p.read_text(encoding="utf-8"))
            self.assertNotIn("password", raw)      # لا حقل كلمة مرور
            self.assertIsInstance(raw["remember_password"], bool)  # علم منطقي فقط
            self.assertEqual(load_config(p).username, "wmo_xx")

    def test_unknown_and_password_keys_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text(json.dumps({"host": "h", "password": "x", "junk": 1}), encoding="utf-8")
            cfg = load_config(p)
            self.assertFalse(hasattr(cfg, "password"))

    def test_validation(self):
        with self.assertRaises(ConfigError):
            AppConfig(port=0).validate()
        with self.assertRaises(ConfigError):
            AppConfig(protocol="sftp").validate()

    def test_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(p)

    def test_malformed_numeric_values_raise_config_error(self):
        for kwargs in (
            {"port": None}, {"port": True}, {"timeout_seconds": "soon"},
            {"max_retries": []}, {"max_parallel": 1.5}, {"min_free_gb": None},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConfigError):
                AppConfig(**kwargs).validate()

    def test_malformed_filter_lists_raise_config_error(self):
        for kwargs in (
            {"selected_kinds": None}, {"selected_kinds": "FP"},
            {"selected_kinds": ["FP", 3]}, {"selected_cycles": {"00"}},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConfigError):
                AppConfig(**kwargs).validate()

    def test_load_config_wraps_malformed_values_as_config_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text(json.dumps({"port": None}), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(p)



class FakeKeyring:
    def __init__(self):
        self.d = {}

    def get_password(self, s, u):
        return self.d.get((s, u))

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def delete_password(self, s, u):
        del self.d[(s, u)]


class SecretsTests(unittest.TestCase):
    def test_roundtrip(self):
        s = SecretStore(FakeKeyring())
        self.assertTrue(s.set_password("u", "pw"))
        self.assertEqual(s.get_password("u"), "pw")
        self.assertTrue(s.delete_password("u"))
        self.assertIsNone(s.get_password("u"))

    def test_postgres_dsn_uses_credential_vault(self):
        backend = FakeKeyring()
        store = SecretStore(backend)
        dsn = "host=127.0.0.1 dbname=ecmwf_webp user=ecmwf_app password=hidden"
        self.assertTrue(store.set_postgres_dsn(dsn))
        self.assertEqual(store.get_postgres_dsn(), dsn)
        self.assertTrue(store.delete_postgres_dsn())
        self.assertIsNone(store.get_postgres_dsn())

    def test_backend_errors_do_not_raise(self):
        class Broken:
            def get_password(self, *a):
                raise RuntimeError("no backend")
        self.assertIsNone(SecretStore(Broken()).get_password("u"))


class LoggingTests(unittest.TestCase):
    def tearDown(self):
        clear_secrets()

    def test_registered_secret_redacted(self):
        register_secret("hunter2-xyz")
        self.assertNotIn("hunter2-xyz", redact("login with hunter2-xyz now"))

    def test_pass_command_redacted(self):
        self.assertNotIn("abc123", redact("*cmd* 'PASS abc123'"))

    def test_log_file_has_no_password(self):
        register_secret("TopSecret99")
        with tempfile.TemporaryDirectory() as d:
            f = setup_logging(Path(d))
            logging.getLogger("t").error("failed with TopSecret99 password=TopSecret99")
            for h in logging.getLogger().handlers:
                h.flush()
            text = f.read_text(encoding="utf-8")
            self.assertIn("failed", text)
            self.assertNotIn("TopSecret99", text)
            self.assertIn("UTC", text)
            for h in list(logging.getLogger().handlers):
                if h.__class__.__name__ == "RotatingFileHandler":
                    logging.getLogger().removeHandler(h)
                    h.close()


if __name__ == "__main__":
    unittest.main()
