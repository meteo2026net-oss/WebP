"""PostgreSQL persistence for forecaster review transitions.

The caller MUST derive actor_id and role from a trusted server-side identity
provider. Never pass client-supplied role claims directly to this repository.
Each state change and its audit event are committed in one transaction.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .review_workflow import (
    ReviewCase,
    ReviewEvent,
    ReviewWorkflowError,
    assign_review,
    comment_review,
    decide_review,
    open_review,
    reopen_review,
)


class ReviewNotFoundError(ReviewWorkflowError):
    """Raised when a review case or its forecast field does not exist."""


class PostgresReviewRepository:
    """Persist review workflow transitions using psycopg 3.

    Args:
        connect: A trusted connection factory, usually a configured pool
            connection method or a callable wrapping psycopg.connect.
    """

    def __init__(self, connect: Callable[[], psycopg.Connection[Any]]) -> None:
        self._connect = connect

    @staticmethod
    def _case_from_row(row: dict[str, Any]) -> ReviewCase:
        return ReviewCase(
            review_id=str(row["review_id"]),
            field_id=row["field_id"],
            status=row["status"],
            assigned_to=row["assigned_to"],
            review_version=row["review_version"],
            decided_by=row["decided_by"],
            decided_at=(
                row["decided_at"].isoformat() if row["decided_at"] is not None else None
            ),
            decision_reason=row["decision_reason"],
        )

    def get_case(self, review_id: UUID | str) -> ReviewCase:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT review_id, field_id, status, assigned_to, review_version,
                           decided_by, decided_at, decision_reason
                    FROM weather.review_case WHERE review_id = %s
                    """,
                    (str(review_id),),
                )
                row = cur.fetchone()
                if row is None:
                    raise ReviewNotFoundError(f"review case {review_id} was not found")
                case = self._case_from_row(row)
                cur.execute(
                    """
                    SELECT actor_id, event_type, note, annotation, created_at
                    FROM weather.review_event
                    WHERE review_id = %s ORDER BY created_at, event_id
                    """,
                    (str(review_id),),
                )
                case.events = [
                    ReviewEvent(
                        actor_id=item["actor_id"],
                        event_type=item["event_type"],
                        note=item["note"],
                        annotation=item["annotation"] or {},
                        created_at=item["created_at"].isoformat(),
                    )
                    for item in cur.fetchall()
                ]
                return case

    def transition(
        self,
        review_id: UUID | str,
        *,
        operation: str,
        actor_id: str,
        role: str,
        expected_version: int,
        **kwargs: Any,
    ) -> ReviewCase:
        """Apply one domain transition and append its audit event atomically.

        actor_id/role must already have been resolved by trusted server code.
        Approval quality is read from the database while the field row is
        locked, not accepted from the request payload.
        """
        operations = {
            "assign": assign_review,
            "open": open_review,
            "comment": comment_review,
            "decide": decide_review,
            "reopen": reopen_review,
        }
        if operation not in operations:
            raise ReviewWorkflowError(f"unsupported review operation: {operation!r}")

        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        SELECT review_id, field_id, status, assigned_to, review_version,
                               decided_by, decided_at, decision_reason
                        FROM weather.review_case
                        WHERE review_id = %s
                        FOR UPDATE
                        """,
                        (str(review_id),),
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise ReviewNotFoundError(f"review case {review_id} was not found")

                    case = self._case_from_row(row)
                    old_version = case.review_version
                    transition_kwargs = dict(kwargs)
                    if operation == "decide" and transition_kwargs.get("decision") == "approved":
                        cur.execute(
                            """
                            SELECT quality_status FROM weather.field
                            WHERE field_id = %s FOR SHARE
                            """,
                            (case.field_id,),
                        )
                        quality = cur.fetchone()
                        if quality is None:
                            raise ReviewNotFoundError(
                                f"forecast field {case.field_id} was not found"
                            )
                        transition_kwargs["quality_status"] = quality["quality_status"]

                    operations[operation](
                        case,
                        actor_id=actor_id,
                        role=role,
                        expected_version=expected_version,
                        **transition_kwargs,
                    )
                    event = case.events[-1]
                    cur.execute(
                        """
                        UPDATE weather.review_case
                        SET status = %s, assigned_to = %s, review_version = %s,
                            decided_by = %s, decided_at = %s, decision_reason = %s
                        WHERE review_id = %s AND review_version = %s
                        """,
                        (
                            case.status,
                            case.assigned_to,
                            case.review_version,
                            case.decided_by,
                            case.decided_at,
                            case.decision_reason,
                            str(review_id),
                            old_version,
                        ),
                    )
                    if cur.rowcount != 1:
                        raise ReviewWorkflowError("review version changed during transition")
                    cur.execute(
                        """
                        INSERT INTO weather.review_event
                            (review_id, actor_id, event_type, note, annotation)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            str(review_id),
                            event.actor_id,
                            event.event_type,
                            event.note,
                            json.dumps(event.annotation, ensure_ascii=False),
                        ),
                    )
        return self.get_case(review_id)

    def list_queue(
        self,
        *,
        statuses: tuple[str, ...] = ("pending", "in_review", "changes_requested"),
        assigned_to: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not statuses:
            return []
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT r.review_id, r.field_id, r.status, r.assigned_to,
                           r.review_version, r.submitted_at, f.quality_status,
                           f.valid_time, f.forecast_hour
                    FROM weather.review_case AS r
                    JOIN weather.field AS f ON f.field_id = r.field_id
                    WHERE r.status = ANY(%s)
                      AND (%s IS NULL OR r.assigned_to = %s)
                    ORDER BY r.submitted_at, r.review_id
                    LIMIT %s
                    """,
                    (list(statuses), assigned_to, assigned_to, limit),
                )
                return list(cur.fetchall())

    def list_publishable_fields(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Read only from the QC+human-approval view; DB grants remain required."""
        if not 1 <= limit <= 2000:
            raise ValueError("limit must be between 1 and 2000")
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM weather.publishable_field
                    ORDER BY valid_time DESC, field_id DESC LIMIT %s
                    """,
                    (limit,),
                )
                return list(cur.fetchall())
