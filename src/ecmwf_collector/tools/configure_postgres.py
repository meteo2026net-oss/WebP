"""Provision a restricted PostgreSQL app login and store it in the OS credential vault."""
from __future__ import annotations

import argparse
import json
import getpass
import sys

from ecmwf_collector.postgres_provision import (
    provision_application_login, remove_new_application_login,
)
from ecmwf_collector.logging_setup import redact, register_secret
from ecmwf_collector.secrets_store import SecretStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true", help="Remove the saved PostgreSQL DSN.")
    parser.add_argument(
        "--diagnose", action="store_true",
        help="Print read-only diagnostics for locally installed PostgreSQL tools and services.",
    )
    args = parser.parse_args()
    if args.diagnose:
        from ecmwf_collector.postgres_windows import diagnose_postgres_installation

        result = diagnose_postgres_installation()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["server_installation_detected"]:
            print(
                "لم يتم اكتشاف خادم PostgreSQL محلي. هذا الفحص لا يثبت الخادم ولا يغيّر الخدمات."
            )
            return 1
        return 0
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
    role_provisioned = False
    try:
        # Provision and verify a restricted application login. Never persist
        # the administrator DSN in the operating-system credential vault.
        app_dsn = provision_application_login(admin_dsn)
        role_provisioned = True
        if not secrets.set_postgres_dsn(app_dsn):
            remove_new_application_login(admin_dsn)
            role_provisioned = False
            print("Could not save the application login in the OS credential vault; the newly created app role was removed. The PostgreSQL table and data were retained.", file=sys.stderr)
            return 3
        print("A least-privilege PostgreSQL application login was verified and saved.")
        print("The administrator DSN was not stored.")
        print("The application will use the restricted login on its next launch.")
        return 0
    except Exception as exc:
        if role_provisioned:
            try:
                remove_new_application_login(admin_dsn)
            except Exception:
                print("Warning: app-role cleanup could not be confirmed; inspect PostgreSQL role ecmwf_webp_app before retrying.", file=sys.stderr)
        print(f"PostgreSQL setup failed ({type(exc).__name__}): {redact(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
