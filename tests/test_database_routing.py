import json
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.connection_profiles import DatabaseProfile, DatabaseProfileStore
from ecmwf_collector.database_routing import DatabaseRoutingError, DatabaseRoutingStore


class DatabaseRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.profiles = DatabaseProfileStore(root / "profiles.json")
        self.first = DatabaseProfile.create("Local", "sqlite", sqlite_path=str(root / "local.db"))
        self.second = DatabaseProfile.create("Archive", "sqlite", sqlite_path=str(root / "archive.db"))
        self.profiles.save(self.first)
        self.profiles.save(self.second)
        self.path = root / "routing.json"
        self.routes = DatabaseRoutingStore(self.path, self.profiles)

    def test_route_resolves_selected_profile_and_persists(self):
        key = self.routes.model_key("ECMWF", "IFS HRES", "GRIB")
        self.routes.set_route(key, self.first.profile_id)
        reloaded = DatabaseRoutingStore(self.path, self.profiles)
        self.assertEqual(reloaded.resolve(key), self.first.profile_id)

    def test_default_profile_is_used_only_when_no_specific_route_exists(self):
        key = self.routes.model_key("NOAA", "GFS")
        self.routes.set_default(self.first.profile_id)
        self.assertEqual(self.routes.resolve(key), self.first.profile_id)
        self.routes.set_route(key, self.second.profile_id)
        self.assertEqual(self.routes.resolve(key), self.second.profile_id)

    def test_disabled_profile_is_rejected_when_assigning_route(self):
        disabled = DatabaseProfile(**{**self.second.to_metadata(), "enabled": False})
        self.profiles.save(disabled)
        with self.assertRaises(DatabaseRoutingError):
            self.routes.set_route("noaa::gfs::default", disabled.profile_id)

    def test_disabled_or_deleted_profile_does_not_silently_fallback(self):
        key = "ecmwf::aifs single::grib"
        self.routes.set_default(self.first.profile_id)
        self.routes.set_route(key, self.second.profile_id)
        self.profiles.save(DatabaseProfile(**{**self.second.to_metadata(), "enabled": False}))
        with self.assertRaises(DatabaseRoutingError):
            self.routes.resolve(key)

    def test_profile_removal_clears_explicit_references(self):
        self.routes.set_default(self.first.profile_id)
        self.routes.set_route("ecmwf::ifs::grib", self.first.profile_id)
        removed = self.routes.remove_profile_references(self.first.profile_id)
        self.assertEqual(removed, 2)
        self.assertIsNone(self.routes.resolve("ecmwf::ifs::grib"))

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(DatabaseRoutingError):
            self.routes.set_default("not-registered")

    def test_route_file_contains_no_credentials(self):
        self.routes.set_route("ecmwf::ifs::grib", self.first.profile_id)
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("password", raw.lower())
        self.assertNotIn("postgresql://", raw)


if __name__ == "__main__":
    unittest.main()
