"""Configure the local PostgreSQL DSN without writing credentials to disk."""
from __future__ import annotations

import argparse
import getpass
import sys

from ecmwf_collector.postgres_state import PostgresStateStore
from ecmwf_collector.secrets_store import SecretStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true", help="Remove the saved PostgreSQL DSN.")
    args = parser.parse_args()
    secrets = SecretStore()
    if args.remove:
        if not secrets.available:
            print("OS credential vault is unavailable; nothing was changed.", file=sys.stderr)
            return 2
        removed = secrets.delete_postgres_dsn()
        print("Saved PostgreSQL connection removed." if removed else "No saved connection was removed.")
        return 0 if removed else 1

    if not secrets.available:
        print(
            "The operating-system credential vault is unavailable. "
            "Install/use a supported keyring backend or set ECMWF_POSTGRES_DSN for this session.",
            file=sys.stderr,
        )
        return 2

    dsn = getpass.getpass("PostgreSQL connection string (input hidden): ").strip()
    if not dsn:
        print("No connection string supplied.", file=sys.stderr)
        return 2

    store = None
    try:
        # Verify reachability and credentials before persisting anything.
        store = PostgresStateStore(dsn)
        if not secrets.set_postgres_dsn(dsn):
            print("Could not save the connection in the OS credential vault.", file=sys.stderr)
            return 3
        print("PostgreSQL connection verified and saved in the OS credential vault.")
        print("The application will use it automatically on its next launch.")
        return 0
    except Exception as exc:
        print(f"PostgreSQL setup failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
