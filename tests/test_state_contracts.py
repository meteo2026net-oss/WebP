import unittest

from ecmwf_collector.postgres_state import PostgresStateStore
from ecmwf_collector.state import StateStore
from ecmwf_collector.state_contracts import StateStoreProtocol


class StateStoreContractTests(unittest.TestCase):
    def test_sqlite_store_implements_common_contract(self):
        self.assertTrue(issubclass(StateStore, StateStoreProtocol))

    def test_postgres_store_implements_common_contract(self):
        self.assertTrue(issubclass(PostgresStateStore, StateStoreProtocol))


if __name__ == "__main__":
    unittest.main()
