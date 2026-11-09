"""Development-only WSGI entry point for the Codespaces review integration stack."""
from __future__ import annotations

import os

from ecmwf_collector.oidc_identity import OIDCSettings
from ecmwf_collector.postgres_review_runtime import create_review_runtime

required = ("ECMWF_REVIEW_DATABASE_DSN",)
missing = [name for name in required if not os.environ.get(name)]
if missing:
    raise RuntimeError("Missing environment variables: " + ", ".join(missing))

settings = OIDCSettings.from_env()
runtime = create_review_runtime(
    dsn=os.environ["ECMWF_REVIEW_DATABASE_DSN"],
    oidc_settings=settings,
    min_pool_size=1,
    max_pool_size=4,
)
application = runtime.application
