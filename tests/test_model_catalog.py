"""Tests for the numerical model inventory and honest integration statuses."""
import unittest

from ecmwf_collector.model_catalog import (
    IMPLEMENTATION_LABELS, MODEL_CATALOG, implementation_counts, models_for_provider,
)


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_contains_expected_major_model_families(self):
        names = {(item.provider, item.model) for item in MODEL_CATALOG}
        for expected in (
            ("ECMWF", "IFS HRES"), ("ECMWF", "AIFS Single"),
            ("NOAA", "GFS"), ("NOAA", "GEFS"), ("DWD", "ICON Global"),
            ("JMA", "GSM"), ("Météo-France", "AROME"),
            ("CPTEC/INPE", "ETA"), ("Copernicus", "ERA5"),
        ):
            self.assertIn(expected, names)

    def test_catalog_distinguishes_model_from_reanalysis_and_wms(self):
        by_name = {(item.provider, item.model): item for item in MODEL_CATALOG}
        self.assertEqual(by_name[("Copernicus", "ERA5")].product_type, "إعادة تحليل مناخي")
        self.assertEqual(by_name[("ECMWF", "ecCharts WMS")].implementation, "wms")

    def test_gfs_is_marked_as_direct_grib_adapter(self):
        gfs = next(item for item in MODEL_CATALOG if item.provider == "NOAA" and item.model == "GFS")
        self.assertEqual(gfs.implementation, "adapter")
        self.assertIn("GRIB2 مباشر", gfs.notes)
        self.assertIn("Windy", gfs.notes)

    def test_gefs_is_marked_as_member_aware_grib_adapter_without_claiming_statistics(self):
        gefs = next(item for item in MODEL_CATALOG if item.provider == "NOAA" and item.model == "GEFS")
        self.assertEqual(gefs.implementation, "adapter")
        self.assertIn("p01–p30", gefs.notes)
        self.assertIn("لا يحسب إحصاءات", gefs.notes)

    def test_unimplemented_models_are_explicitly_marked(self):
        self.assertEqual(
            next(item for item in MODEL_CATALOG if item.model == "ICON Global").implementation,
            "planned",
        )
        self.assertIn("planned", implementation_counts())
        self.assertEqual(sum(implementation_counts().values()), len(MODEL_CATALOG))

    def test_provider_filter_is_exact(self):
        self.assertEqual(len(models_for_provider("ECMWF")), 5)
        self.assertEqual(models_for_provider("unknown"), ())

    def test_every_status_has_a_display_label(self):
        self.assertTrue(all(item.implementation in IMPLEMENTATION_LABELS for item in MODEL_CATALOG))


if __name__ == "__main__":
    unittest.main()
