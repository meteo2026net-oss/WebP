"""Application service for authenticated forecaster review operations.

HTTP handlers should inject a trusted identity provider (session/JWT verifier)
and call this service. Never construct actor roles from request-body fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from .postgres_review_repository import PostgresReviewRepository
from .review_workflow import (
    ReviewCase,
    ReviewPermissionError,
    VALID_ROLES,
)


@dataclass(frozen=True)
class AuthenticatedActor:
    """Identity claims resolved by trusted server-side authentication."""

    subject: str
    role: str


class ReviewIdentityProvider(Protocol):
    """Authentication adapter supplied by the eventual HTTP application."""

    def current_actor(self) -> AuthenticatedActor:
        """Return the authenticated principal for the current request."""


class ReviewApplicationService:
    """Authorize access and delegate durable transitions to PostgreSQL."""

    def __init__(
        self,
        repository: PostgresReviewRepository,
        identity_provider: ReviewIdentityProvider,
    ) -> None:
        self._repository = repository
        self._identity_provider = identity_provider

    def _actor(self) -> AuthenticatedActor:
        actor = self._identity_provider.current_actor()
        if not isinstance(actor, AuthenticatedActor):
            raise ReviewPermissionError("authentication provider returned no trusted actor")
        if (
            not isinstance(actor.subject, str)
            or not actor.subject.strip()
            or not isinstance(actor.role, str)
            or actor.role not in VALID_ROLES
        ):
            raise ReviewPermissionError("authenticated actor has invalid identity or role")
        return actor

    def get_case(self, review_id: UUID | str) -> ReviewCase:
        actor = self._actor()
        case = self._repository.get_case(review_id)
        if actor.role not in {"review_lead", "admin"} and (actor.role != "reviewer" or case.assigned_to != actor.subject):
            raise ReviewPermissionError("actor is not authorized to access this review case")
        return case

    def list_queue(self, *, limit: int = 100) -> list[dict[str, Any]]:
        actor = self._actor()
        if actor.role in {"review_lead", "admin"}:
            return self._repository.list_queue(limit=limit)
        if actor.role != "reviewer":
            raise ReviewPermissionError("only reviewers and review leads may access the review queue")
        return self._repository.list_queue(assigned_to=actor.subject, limit=limit)

    def transition(
        self,
        review_id: UUID | str,
        *,
        operation: str,
        expected_version: int,
        **payload: Any,
    ) -> ReviewCase:
        actor = self._actor()
        # The authenticated identity is the only source of actor_id and role.
        # Domain validation rejects role/operation combinations that are invalid.
        return self._repository.transition(
            review_id,
            operation=operation,
            actor_id=actor.subject,
            role=actor.role,
            expected_version=expected_version,
            **payload,
        )

    def list_publishable_fields(self, *, limit: int = 500) -> list[dict[str, Any]]:
        actor = self._actor()
        if actor.role not in {"publisher", "review_lead", "admin"}:
            raise ReviewPermissionError("only publishers, review leads, or admins may read publishable fields")
        return self._repository.list_publishable_fields(limit=limit)
