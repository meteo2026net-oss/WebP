"""State, authorization, audit and optimistic-concurrency tests."""
import unittest

from ecmwf_collector.review_workflow import (
    ReviewCase, ReviewConflictError, ReviewPermissionError, ReviewWorkflowError,
    assign_review, comment_review, decide_review, is_publishable, open_review,
    reopen_review,
)


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.case = ReviewCase("r-1", 42)

    def test_happy_path_assign_open_comment_approve(self):
        assign_review(self.case, actor_id="lead", role="review_lead",
                      reviewer_id="forecaster", expected_version=1)
        open_review(self.case, actor_id="forecaster", role="reviewer", expected_version=2)
        comment_review(self.case, actor_id="forecaster", role="reviewer",
                       note="Checked synoptic consistency", annotation={"region": "north"},
                       expected_version=3)
        decide_review(self.case, actor_id="forecaster", role="reviewer",
                      decision="approved", reason="Quality and synoptic checks passed",
                      expected_version=4, quality_status="passed")
        self.assertEqual(self.case.status, "approved")
        self.assertEqual(self.case.review_version, 5)
        self.assertEqual([e.event_type for e in self.case.events],
                         ["assigned", "opened", "commented", "approved"])
        self.assertEqual(self.case.decided_by, "forecaster")
        self.assertIsNotNone(self.case.decided_at)

    def test_only_lead_can_assign_and_reopen(self):
        with self.assertRaises(ReviewPermissionError):
            assign_review(self.case, actor_id="x", role="reviewer",
                          reviewer_id="y", expected_version=1)

    def test_reviewer_must_be_assigned_before_open_or_decide(self):
        with self.assertRaises(ReviewPermissionError):
            open_review(self.case, actor_id="intruder", role="reviewer", expected_version=1)

    def test_stale_version_rejected_without_mutation(self):
        with self.assertRaises(ReviewConflictError):
            open_review(self.case, actor_id="lead", role="review_lead", expected_version=9)
        self.assertEqual(self.case.status, "pending")
        self.assertEqual(self.case.review_version, 1)

    def test_decision_requires_reason_and_valid_state(self):
        assign_review(self.case, actor_id="lead", role="review_lead",
                      reviewer_id="r", expected_version=1)
        open_review(self.case, actor_id="r", role="reviewer", expected_version=2)
        with self.assertRaises(ReviewWorkflowError):
            decide_review(self.case, actor_id="r", role="reviewer",
                          decision="approved", reason=" ", expected_version=3,
                          quality_status="passed")
        with self.assertRaises(ReviewWorkflowError):
            decide_review(self.case, actor_id="r", role="reviewer",
                          decision="approved", reason="Looks acceptable",
                          expected_version=3, quality_status="pending")

    def test_changes_requested_can_be_reopened_with_new_assignment(self):
        assign_review(self.case, actor_id="lead", role="review_lead",
                      reviewer_id="r", expected_version=1)
        open_review(self.case, actor_id="r", role="reviewer", expected_version=2)
        decide_review(self.case, actor_id="r", role="reviewer",
                      decision="changes_requested", reason="Recheck upper-level field",
                      expected_version=3)
        reopen_review(self.case, actor_id="lead", role="review_lead",
                      reason="New field version submitted", expected_version=4)
        self.assertEqual(self.case.status, "pending")
        self.assertIsNone(self.case.assigned_to)
        self.assertEqual(self.case.events[-1].event_type, "reopened")

    def test_publishability_fails_closed(self):
        self.assertFalse(is_publishable(quality_status="passed", case=None))
        self.assertFalse(is_publishable(quality_status="pending", case=self.case))
        self.assertFalse(is_publishable(quality_status="passed", case=self.case))
        self.case.status = "approved"
        self.assertTrue(is_publishable(quality_status="passed", case=self.case))


    def test_publisher_cannot_perform_review_transitions(self):
        with self.assertRaises(ReviewPermissionError):
            assign_review(self.case, actor_id="publisher", role="publisher",
                          reviewer_id="reviewer", expected_version=1)
        with self.assertRaises(ReviewPermissionError):
            open_review(self.case, actor_id="publisher", role="publisher",
                        expected_version=1)
        with self.assertRaises(ReviewPermissionError):
            comment_review(self.case, actor_id="publisher", role="publisher",
                           note="Not permitted", expected_version=1)
        with self.assertRaises(ReviewPermissionError):
            decide_review(self.case, actor_id="publisher", role="publisher",
                          decision="rejected", reason="Not permitted",
                          expected_version=1)
        with self.assertRaises(ReviewPermissionError):
            reopen_review(self.case, actor_id="publisher", role="publisher",
                          reason="Not permitted", expected_version=1)
        self.assertEqual(self.case.status, "pending")
        self.assertEqual(self.case.review_version, 1)
        self.assertEqual(self.case.events, [])


if __name__ == "__main__":
    unittest.main()
