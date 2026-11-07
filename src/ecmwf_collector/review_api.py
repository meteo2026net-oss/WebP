"""Dependency-free WSGI REST adapter for forecaster review operations.

Authentication is intentionally injected: identity_provider_factory must
validate the deployment's session/token and return a trusted identity provider.
This module never interprets client-supplied role or actor fields.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from typing import Any, Callable
from urllib.parse import parse_qs

from .postgres_review_repository import PostgresReviewRepository, ReviewNotFoundError
from .review_service import ReviewApplicationService, ReviewIdentityProvider
from .review_workflow import ReviewConflictError, ReviewPermissionError, ReviewWorkflowError

_LOG = logging.getLogger(__name__)
_MAX_BODY_BYTES = 1_048_576
_REVIEW_PATH = re.compile(r"^/api/v1/reviews/([^/]+)(?:/(assign|open|comments|decision|reopen))?$")


class ReviewWsgiApplication:
    """WSGI API adapter; inject a verified identity provider per request."""

    def __init__(
        self,
        repository: PostgresReviewRepository,
        identity_provider_factory: Callable[[dict[str, Any]], ReviewIdentityProvider],
    ) -> None:
        self._repository = repository
        self._identity_provider_factory = identity_provider_factory

    @staticmethod
    def _json_default(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if is_dataclass(value):
            return asdict(value)
        raise TypeError(f"cannot JSON encode {type(value).__name__}")

    @classmethod
    def _json_bytes(cls, value: Any) -> bytes:
        return json.dumps(value, default=cls._json_default, ensure_ascii=False).encode("utf-8")

    @classmethod
    def _respond(
        cls,
        start_response: Callable[..., Any],
        status: HTTPStatus,
        payload: Any,
    ) -> list[bytes]:
        body = cls._json_bytes(payload)
        start_response(
            f"{status.value} {status.phrase}",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )
        return [body]

    @staticmethod
    def _read_json(environ: dict[str, Any]) -> dict[str, Any]:
        raw_length = environ.get("CONTENT_LENGTH") or "0"
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > _MAX_BODY_BYTES:
            raise ValueError("request body exceeds the 1 MiB limit")
        stream = environ["wsgi.input"]
        raw = stream.read(length) if length else b"{}"
        if len(raw) != length:
            raise ValueError("request body length does not match Content-Length")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request JSON body must be an object")
        return value

    @staticmethod
    def _expected_version(payload: dict[str, Any]) -> int:
        value = payload.get("expected_version")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("expected_version must be a positive integer")
        return value

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        try:
            method = str(environ.get("REQUEST_METHOD", "GET")).upper()
            path = str(environ.get("PATH_INFO", "/"))
            provider = self._identity_provider_factory(environ)
            service = ReviewApplicationService(self._repository, provider)

            if path == "/api/v1/reviews":
                if method != "GET":
                    return self._respond(start_response, HTTPStatus.METHOD_NOT_ALLOWED,
                                         {"error": "method_not_allowed"})
                query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=False)
                raw_limit = query.get("limit", ["100"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError as exc:
                    raise ValueError("limit must be an integer") from exc
                return self._respond(start_response, HTTPStatus.OK,
                                     {"items": service.list_queue(limit=limit)})

            if path == "/api/v1/publishable/fields":
                if method != "GET":
                    return self._respond(start_response, HTTPStatus.METHOD_NOT_ALLOWED,
                                         {"error": "method_not_allowed"})
                query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=False)
                try:
                    limit = int(query.get("limit", ["500"])[0])
                except ValueError as exc:
                    raise ValueError("limit must be an integer") from exc
                return self._respond(start_response, HTTPStatus.OK,
                                     {"items": service.list_publishable_fields(limit=limit)})

            match = _REVIEW_PATH.fullmatch(path)
            if not match:
                return self._respond(start_response, HTTPStatus.NOT_FOUND,
                                     {"error": "not_found"})
            review_id, action = match.groups()
            if action is None:
                if method != "GET":
                    return self._respond(start_response, HTTPStatus.METHOD_NOT_ALLOWED,
                                         {"error": "method_not_allowed"})
                return self._respond(start_response, HTTPStatus.OK,
                                     asdict(service.get_case(review_id)))
            if method != "POST":
                return self._respond(start_response, HTTPStatus.METHOD_NOT_ALLOWED,
                                     {"error": "method_not_allowed"})

            payload = self._read_json(environ)
            expected_version = self._expected_version(payload)
            operation_by_action = {
                "assign": ("assign", {"reviewer_id"}),
                "open": ("open", set()),
                "comments": ("comment", {"note", "annotation"}),
                "decision": ("decide", {"decision", "reason"}),
                "reopen": ("reopen", {"reason"}),
            }
            operation, allowed = operation_by_action[action]
            allowed_payload = allowed | {"expected_version"}
            unknown = set(payload) - allowed_payload
            if unknown:
                raise ValueError(
                    "unsupported request fields: " + ", ".join(sorted(unknown))
                )
            missing = allowed - set(payload)
            if missing:
                raise ValueError(
                    "missing request fields: " + ", ".join(sorted(missing))
                )
            result = service.transition(
                review_id,
                operation=operation,
                expected_version=expected_version,
                **{key: payload[key] for key in allowed},
            )
            return self._respond(start_response, HTTPStatus.OK, asdict(result))

        except ReviewNotFoundError:
            return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except ReviewPermissionError:
            return self._respond(start_response, HTTPStatus.FORBIDDEN, {"error": "forbidden"})
        except ReviewConflictError:
            return self._respond(start_response, HTTPStatus.CONFLICT, {"error": "version_conflict"})
        except ReviewWorkflowError as exc:
            return self._respond(start_response, HTTPStatus.UNPROCESSABLE_ENTITY,
                                 {"error": "review_validation_failed", "message": str(exc)})
        except (ValueError, TypeError) as exc:
            return self._respond(start_response, HTTPStatus.BAD_REQUEST,
                                 {"error": "invalid_request", "message": str(exc)})
        except PermissionError:
            return self._respond(start_response, HTTPStatus.UNAUTHORIZED,
                                 {"error": "unauthorized"})
        except Exception:
            _LOG.exception("Unhandled review API error")
            return self._respond(start_response, HTTPStatus.INTERNAL_SERVER_ERROR,
                                 {"error": "internal_server_error"})
