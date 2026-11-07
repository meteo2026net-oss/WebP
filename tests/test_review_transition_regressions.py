"""Regression tests for review transition invariants."""
import unittest

from ecmwf_collector.review_workflow import (
    ReviewCase, ReviewPermissionError, assign_review, decide_review, open_review,
)


class ReviewTransitionRegressionTests(unittest.TestCase):
    def test_reassignment_after_changes_requested_clears_old_decision(self):
        case = ReviewCase("r-2", 43)
        assign_review(case, actor_id="lead", role="review_lead",
                      reviewer_id="forecaster-a", expected_version=1)
        open_review(case, actor_id="forecaster-a", role="reviewer", expected_version=2)
        decide_review(case, actor_id="forecaster-a", role="reviewer",
                      decision="changes_requested", reason="Recheck needed",
                      expected_version=3)
        self.assertIsNotNone(case.decided_by)
        assign_review(case, actor_id="lead", role="review_lead",
                      reviewer_id="forecaster-b", expected_version=4)
        self.assertEqual(case.status, "pending")
        self.assertIsNone(case.decided_by)
        self.assertIsNone(case.decided_at)
        self.assertIsNone(case.decision_reason)
        self.assertEqual(case.assigned_to, "forecaster-b")

    def test_reviewer_cannot_assign(self):
        case = ReviewCase("r-3", 44)
        with self.assertRaises(ReviewPermissionError):
            assign_review(case, actor_id="reviewer", role="reviewer",
                          reviewer_id="other", expected_version=1)


if __name__ == "__main__":
    unittest.main()
