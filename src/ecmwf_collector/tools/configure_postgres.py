"""Configure the local PostgreSQL DSN without writing credentials to disk."""
from __future__ import annotations

import argparse
import getpass
import sys

from ecmwf_collector.postgres_provision import provision_application_login
from ecmwf_collector.logging_setup import redact, register_secret
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

    admin_dsn = getpass.getpass(
        "Local PostgreSQL administrator DSN (input hidden): "
    ).strip()
    if not admin_dsn:
        print("No connection string supplied.", file=sys.stderr)
        return 2

    register_secret(admin_dsn)
    try:
        # Provision and verify a restricted application login. Never persist
        # the administrator DSN in the operating-system credential vault.
        app_dsn = provision_application_login(admin_dsn)
        if not secrets.set_postgres_dsn(app_dsn):
            print("Could not save the application login in the OS credential vault.", file=sys.stderr)
            return 3
        print("A least-privilege PostgreSQL application login was verified and saved.")
        print("The administrator DSN was not stored.")
        print("The application will use the restricted login on its next launch.")
        return 0
    except Exception as exc:
        print(f"PostgreSQL setup failed ({type(exc).__name__}): {redact(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
