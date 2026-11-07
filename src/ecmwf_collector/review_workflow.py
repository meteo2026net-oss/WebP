"""Review workflow policy and state transitions for forecaster decisions.

This module is the domain layer only. It does not authenticate users or persist
records; callers must supply identities/roles from a trusted server-side auth
system and persist each successful transition and event transactionally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class ReviewWorkflowError(ValueError):
    """Base error for invalid review operations."""


class ReviewPermissionError(ReviewWorkflowError):
    """Raised when an actor is not permitted to perform an operation."""


class ReviewConflictError(ReviewWorkflowError):
    """Raised when the caller's expected version is stale."""


VALID_ROLES = frozenset({"reviewer", "review_lead", "admin"})
TERMINAL_STATES = frozenset({"approved", "rejected"})


@dataclass
class ReviewEvent:
    actor_id: str
    event_type: str
    note: str | None = None
    annotation: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


@dataclass
class ReviewCase:
    review_id: str
    field_id: int
    status: str = "pending"
    assigned_to: str | None = None
    review_version: int = 1
    decided_by: str | None = None
    decided_at: str | None = None
    decision_reason: str | None = None
    events: list[ReviewEvent] = field(default_factory=list)


def _required_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewWorkflowError(f"{label} must be a non-empty string")
    return value.strip()


def _authorize(actor_id: str, role: str) -> tuple[str, str]:
    actor = _required_text(actor_id, "actor_id")
    if role not in VALID_ROLES:
        raise ReviewPermissionError(f"unsupported role: {role!r}")
    return actor, role


def _check_version(case: ReviewCase, expected_version: int) -> None:
    if expected_version != case.review_version:
        raise ReviewConflictError(
            f"stale review version: expected {expected_version}, current {case.review_version}"
        )


def _can_review(case: ReviewCase, actor: str, role: str) -> bool:
    return role in {"review_lead", "admin"} or case.assigned_to == actor


def assign_review(
    case: ReviewCase, *, actor_id: str, role: str, reviewer_id: str,
    expected_version: int,
) -> ReviewCase:
    actor, role = _authorize(actor_id, role)
    reviewer = _required_text(reviewer_id, "reviewer_id")
    _check_version(case, expected_version)
    if role not in {"review_lead", "admin"}:
        raise ReviewPermissionError("only review_lead or admin may assign a case")
    if case.status in TERMINAL_STATES:
        raise ReviewWorkflowError("terminal review cases cannot be reassigned")
    if case.status not in {"pending", "in_review", "changes_requested"}:
        raise ReviewWorkflowError(f"cannot assign a case in state {case.status!r}")
    case.assigned_to = reviewer
    case.status = "pending" if case.status == "changes_requested" else case.status
    case.review_version += 1
    case.events.append(ReviewEvent(actor, "assigned", annotation={"reviewer_id": reviewer}))
    return case


def open_review(
    case: ReviewCase, *, actor_id: str, role: str, expected_version: int,
) -> ReviewCase:
    actor, role = _authorize(actor_id, role)
    _check_version(case, expected_version)
    if not _can_review(case, actor, role):
        raise ReviewPermissionError("case is not assigned to this reviewer")
    if case.status not in {"pending", "changes_requested"}:
        raise ReviewWorkflowError(f"cannot open a case in state {case.status!r}")
    case.status = "in_review"
    case.review_version += 1
    case.events.append(ReviewEvent(actor, "opened"))
    return case


def comment_review(
    case: ReviewCase, *, actor_id: str, role: str, note: str,
    annotation: dict[str, Any] | None = None, expected_version: int,
) -> ReviewCase:
    actor, role = _authorize(actor_id, role)
    _check_version(case, expected_version)
    if not _can_review(case, actor, role):
        raise ReviewPermissionError("case is not assigned to this reviewer")
    if case.status != "in_review":
        raise ReviewWorkflowError("comments require an in_review case")
    message = _required_text(note, "note")
    if annotation is not None and not isinstance(annotation, dict):
        raise ReviewWorkflowError("annotation must be a JSON-object-like dictionary")
    case.review_version += 1
    case.events.append(ReviewEvent(actor, "commented", message, annotation or {}))
    return case


def decide_review(
    case: ReviewCase, *, actor_id: str, role: str, decision: str,
    reason: str, expected_version: int, quality_status: str | None = None,
) -> ReviewCase:
    actor, role = _authorize(actor_id, role)
    _check_version(case, expected_version)
    if role not in {"reviewer", "review_lead", "admin"} or not _can_review(case, actor, role):
        raise ReviewPermissionError("actor is not authorized to decide this review")
    if case.status != "in_review":
        raise ReviewWorkflowError("a decision requires an in_review case")
    reason_text = _required_text(reason, "decision reason")
    transitions = {
        "approved": "approved",
        "rejected": "rejected",
        "changes_requested": "changes_requested",
    }
    if decision not in transitions:
        raise ReviewWorkflowError(f"unsupported decision: {decision!r}")
    if decision == "approved" and quality_status != "passed":
        raise ReviewWorkflowError(
            "approval requires server-verified automated quality_status='passed'"
        )
    case.status = transitions[decision]
    case.review_version += 1
    case.decided_by = actor
    case.decided_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    case.decision_reason = reason_text
    case.events.append(ReviewEvent(actor, decision, reason_text))
    return case


def reopen_review(
    case: ReviewCase, *, actor_id: str, role: str, reason: str,
    expected_version: int,
) -> ReviewCase:
    actor, role = _authorize(actor_id, role)
    _check_version(case, expected_version)
    if role not in {"review_lead", "admin"}:
        raise ReviewPermissionError("only review_lead or admin may reopen a case")
    if case.status not in TERMINAL_STATES | {"changes_requested"}:
        raise ReviewWorkflowError(f"cannot reopen a case in state {case.status!r}")
    message = _required_text(reason, "reopen reason")
    case.status = "pending"
    case.assigned_to = None
    case.decided_by = None
    case.decided_at = None
    case.decision_reason = None
    case.review_version += 1
    case.events.append(ReviewEvent(actor, "reopened", message))
    return case


def is_publishable(*, quality_status: str, case: ReviewCase | None) -> bool:
    """Fail closed: quality must pass and the current review must be approved."""
    return quality_status == "passed" and case is not None and case.status == "approved"
