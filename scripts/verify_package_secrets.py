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
}
FORBIDDEN_SUFFIXES = {".sqlite", ".sqlite3", ".p12", ".pfx", ".key"}
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
        lowered_parts = [part.lower() for part in relative.parts]
        name = path.name.lower()
        if name in FORBIDDEN_NAMES or name.startswith(".env."):
            findings.append(f"forbidden credential/state file: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"forbidden credential/database file type: {relative}")
        try:
            content = path.read_bytes()
        except OSError as exc:
            findings.append(f"could not inspect {relative}: {type(exc).__name__}")
            continue
        if DSN_WITH_PASSWORD.search(content):
            findings.append(f"database DSN containing a password: {relative}")
        if PRIVATE_KEY_HEADER.search(content):
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
