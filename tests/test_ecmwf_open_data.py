import tempfile, unittest
from pathlib import Path
from ecmwf_collector.sources.ecmwf_open_data import retrieve_open_data

class OpenDataTests(unittest.TestCase):
    def test_requires_param_and_step(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                retrieve_open_data({"type":"fc"},Path(d)/"x.grib",client_factory=object)
    def test_source_metadata_contract(self):
        # Keep the contract test independent from network and ECMWF availability.
        from ecmwf_collector.sources import ecmwf_open_data
        self.assertEqual(ecmwf_open_data.__doc__.split(";")[0],"ECMWF Open Data client")
        self.assertTrue(callable(retrieve_open_data))
if __name__=="__main__": unittest.main()
