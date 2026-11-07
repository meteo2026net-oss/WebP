"""Production-oriented PostgreSQL pool and OIDC review API assembly.

This module is optional server runtime glue; it is not imported by the desktop GUI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .oidc_identity import OIDCSettings, oidc_identity_provider_factory
from .postgres_review_repository import PostgresReviewRepository
from .review_api import ReviewWsgiApplication


@dataclass
class ReviewRuntime:
    application: ReviewWsgiApplication
    pool: Any

    def close(self) -> None:
        self.pool.close()


def create_review_runtime(
    *,
    dsn: str,
    oidc_settings: OIDCSettings,
    min_pool_size: int = 1,
    max_pool_size: int = 8,
    timeout_seconds: float = 10.0,
) -> ReviewRuntime:
    """Create a pooled WSGI review app; require verified TLS for database traffic."""
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("a PostgreSQL DSN is required")
    if not 1 <= min_pool_size <= max_pool_size <= 32:
        raise ValueError("pool sizes must satisfy 1 <= min <= max <= 32")
    if timeout_seconds <= 0 or timeout_seconds > 60:
        raise ValueError("pool timeout must be between 0 and 60 seconds")

    from psycopg.conninfo import conninfo_to_dict
    options = conninfo_to_dict(dsn)
    sslmode = options.get("sslmode", "prefer")
    if sslmode not in {"verify-full", "verify-ca"}:
        raise ValueError("review API PostgreSQL connections require sslmode=verify-full or verify-ca")
    if not options.get("host"):
        raise ValueError("review API PostgreSQL DSN must specify a database host")

    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "review API runtime requires the optional psycopg_pool dependency"
        ) from exc

    pool = ConnectionPool(
        conninfo=dsn,
        min_size=min_pool_size,
        max_size=max_pool_size,
        timeout=timeout_seconds,
        open=True,
    )
    repository = PostgresReviewRepository(pool.connection)
    application = ReviewWsgiApplication(
        repository, oidc_identity_provider_factory(oidc_settings)
    )
    return ReviewRuntime(application=application, pool=pool)
