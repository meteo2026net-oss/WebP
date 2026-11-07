"""Authorization boundary tests for the review application service."""
import unittest
from unittest.mock import Mock

from ecmwf_collector.review_service import (
    AuthenticatedActor,
    ReviewApplicationService,
)
from ecmwf_collector.review_workflow import ReviewCase, ReviewPermissionError


class StaticIdentityProvider:
    def __init__(self, actor):
        self.actor = actor

    def current_actor(self):
        return self.actor


class ReviewApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.repository = Mock()
        self.identity = StaticIdentityProvider(
            AuthenticatedActor(subject="forecaster-1", role="reviewer")
        )
        self.service = ReviewApplicationService(self.repository, self.identity)

    def test_reviewer_queue_is_scoped_to_authenticated_subject(self):
        self.repository.list_queue.return_value = []
        self.service.list_queue(limit=25)
        self.repository.list_queue.assert_called_once_with(
            assigned_to="forecaster-1", limit=25
        )

    def test_lead_queue_is_not_scoped_to_single_assignee(self):
        self.identity.actor = AuthenticatedActor(subject="lead-1", role="review_lead")
        self.repository.list_queue.return_value = []
        self.service.list_queue()
        self.repository.list_queue.assert_called_once_with(limit=100)

    def test_case_access_is_restricted_for_unassigned_reviewer(self):
        self.repository.get_case.return_value = ReviewCase(
            "r-9", 90, assigned_to="another-reviewer"
        )
        with self.assertRaises(ReviewPermissionError):
            self.service.get_case("r-9")

    def test_transition_identity_comes_only_from_identity_provider(self):
        self.repository.transition.return_value = ReviewCase("r-9", 90)
        self.service.transition(
            "r-9", operation="open", expected_version=2
        )
        args = self.repository.transition.call_args
        self.assertEqual(args.kwargs["actor_id"], "forecaster-1")
        self.assertEqual(args.kwargs["role"], "reviewer")
        self.assertNotIn("actor_id", args.kwargs.get("payload", {}))

    def test_missing_trusted_actor_is_rejected(self):
        self.identity.actor = {"subject": "attacker", "role": "admin"}
        with self.assertRaises(ReviewPermissionError):
            self.service.list_queue()


if __name__ == "__main__":
    unittest.main()
