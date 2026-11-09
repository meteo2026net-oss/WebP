"""OIDC/JWKS bearer authentication adapter for the forecaster review API.

Only asymmetric RS256 tokens from the configured issuer are accepted. Roles are
mapped from one configured claim using a server-owned allowlist; client JSON,
query parameters, and forwarded identity headers are never consulted.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .review_service import AuthenticatedActor
from .review_workflow import VALID_ROLES


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    audience: str
    jwks_url: str
    role_claim: str
    role_mapping: dict[str, str]
    leeway_seconds: int = 30
    max_token_bytes: int = 16_384

    def __post_init__(self) -> None:
        for label, value in (("issuer", self.issuer), ("jwks_url", self.jwks_url)):
            parsed = urlparse(value)
            is_https = parsed.scheme == "https"
            is_loopback_jwks = (
                label == "jwks_url"
                and parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            )
            if (
                not (is_https or is_loopback_jwks)
                or not parsed.netloc
                or parsed.username
                or parsed.password
            ):
                raise ValueError(
                    f"OIDC {label} must be HTTPS, except JWKS may use HTTP on loopback only"
                )
        if not self.audience.strip() or not self.role_claim.strip():
            raise ValueError("OIDC audience and role claim are required")
        if not self.role_mapping or any(role not in VALID_ROLES for role in self.role_mapping.values()):
            raise ValueError("OIDC role mapping must map configured claims to known review roles")
        if self.leeway_seconds < 0 or self.leeway_seconds > 120:
            raise ValueError("OIDC leeway must be between 0 and 120 seconds")
        if self.max_token_bytes < 1024 or self.max_token_bytes > 65536:
            raise ValueError("OIDC token size limit is outside the safe range")

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "OIDCSettings":
        env = os.environ if environ is None else environ
        raw_mapping = env.get("ECMWF_OIDC_ROLE_MAPPING", "")
        try:
            mapping = json.loads(raw_mapping)
        except json.JSONDecodeError as exc:
            raise ValueError("ECMWF_OIDC_ROLE_MAPPING must be a JSON object") from exc
        if not isinstance(mapping, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in mapping.items()
        ):
            raise ValueError("ECMWF_OIDC_ROLE_MAPPING must contain string claim-to-role entries")
        return cls(
            issuer=env.get("ECMWF_OIDC_ISSUER", ""),
            audience=env.get("ECMWF_OIDC_AUDIENCE", ""),
            jwks_url=env.get("ECMWF_OIDC_JWKS_URL", ""),
            role_claim=env.get("ECMWF_OIDC_ROLE_CLAIM", "review_role"),
            role_mapping=mapping,
        )


class OIDCIdentityProvider:
    """Validate one request's Authorization: Bearer token against configured OIDC."""

    def __init__(self, environ: dict[str, Any], settings: OIDCSettings, jwks_client: Any = None):
        self._environ = environ
        self._settings = settings
        self._jwks_client = jwks_client

    def _client(self):
        if self._jwks_client is None:
            try:
                import jwt
            except ImportError as exc:
                raise RuntimeError(
                    "OIDC review authentication requires the optional PyJWT[crypto] dependency"
                ) from exc
            self._jwks_client = jwt.PyJWKClient(
                self._settings.jwks_url, cache_jwk_set=True, timeout=5
            )
        return self._jwks_client

    def current_actor(self) -> AuthenticatedActor:
        authorization = str(self._environ.get("HTTP_AUTHORIZATION", ""))
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token or " " in token:
            raise PermissionError("a bearer access token is required")
        if len(token.encode("ascii", errors="ignore")) != len(token) or len(token) > self._settings.max_token_bytes:
            raise PermissionError("invalid bearer token")
        try:
            import jwt
            signing_key = self._client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                leeway=self._settings.leeway_seconds,
                options={"require": ["exp", "iat", "sub"]},
            )
        except ImportError as exc:
            raise RuntimeError(
                "OIDC review authentication requires the optional PyJWT[crypto] dependency"
            ) from exc
        except Exception as exc:
            raise PermissionError("bearer token validation failed") from exc

        subject = claims.get("sub")
        role_value = claims.get(self._settings.role_claim)
        role = self._settings.role_mapping.get(role_value) if isinstance(role_value, str) else None
        if not isinstance(subject, str) or not subject.strip() or role not in VALID_ROLES:
            raise PermissionError("token has no recognized subject and review role")
        return AuthenticatedActor(subject=subject, role=role)


def oidc_identity_provider_factory(settings: OIDCSettings):
    """Return a request-scoped provider factory with a shared rotating JWKS cache."""
    client_lock = threading.Lock()
    shared_client: list[Any] = []

    def factory(environ: dict[str, Any]) -> OIDCIdentityProvider:
        if not shared_client:
            with client_lock:
                if not shared_client:
                    try:
                        import jwt
                    except ImportError as exc:
                        raise RuntimeError(
                            "OIDC review authentication requires the optional PyJWT[crypto] dependency"
                        ) from exc
                    shared_client.append(jwt.PyJWKClient(
                        settings.jwks_url, cache_jwk_set=True, timeout=5
                    ))
        return OIDCIdentityProvider(environ, settings, jwks_client=shared_client[0])

    return factory
