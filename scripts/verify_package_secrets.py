"""Fail a portable build if user credential stores or private keys enter the package."""
from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN_NAMES = {
    ".env",
    "database-profiles.json",
    "database-routing.json",
    "state.db",
    "credentials.json",
    ".pgpass",
    ".my.cnf",
    ".netrc",
    "id_rsa",
    "id_ed25519",
}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".p12", ".pfx", ".key"}
DSN_WITH_PASSWORD = re.compile(
    rb"(?i)(?:postgres(?:ql)?|mysql|mariadb)://[^\s/:@]+:[^\s/@]+@"
)
PRIVATE_KEY_HEADER = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)


def scan_package(root: Path) -> list[str]:
    root = Path(root)
    if not root.is_dir():
        return [f"package directory does not exist: {root}"]
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = [part.lower() for part in relative.parts]
        name = path.name.lower()
        if (name in FORBIDDEN_NAMES or name.startswith(".env.")
                or any(part == ".env" or part.startswith(".env.") for part in parts)
                or any(part in {".ssh", ".aws"} for part in parts)):
            findings.append(f"forbidden credential/state file: {relative}")
        # PROJ's bundled coordinate reference database is public geospatial
        # data, not an application credential/state database.
        is_public_proj_data = (
            path.suffix.lower() == ".db"
            and tuple(part.lower() for part in relative.parts[-5:])
            == ("pyproj", "proj_dir", "share", "proj", "proj.db")
        )
        if path.suffix.lower() in FORBIDDEN_SUFFIXES and not is_public_proj_data:
            findings.append(f"forbidden credential/database file type: {relative}")
        try:
            content = path.read_bytes()
        except OSError as exc:
            findings.append(f"could not inspect {relative}: {type(exc).__name__}")
            continue
        if DSN_WITH_PASSWORD.search(content):
            findings.append(f"database DSN containing a password: {relative}")
        # PE/DLL binaries can contain coincidental PEM marker byte sequences.
        # Inspect private-key headers in text-like files only; DSN scanning
        # above remains byte-based for every packaged file.
        if 0 not in content and PRIVATE_KEY_HEADER.search(content):
            findings.append(f"private key material: {relative}")
    return findings


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: python scripts/verify_package_secrets.py <package-directory>", file=sys.stderr)
        return 2
    findings = scan_package(Path(args[0]))
    if findings:
        for finding in findings:
            print(f"SECURITY FAILURE: {finding}", file=sys.stderr)
        return 1
    print("Package security scan passed: no credential stores, database state files, password DSNs, or private keys found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
