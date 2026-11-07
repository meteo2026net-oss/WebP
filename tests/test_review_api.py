"""HTTP contract tests for the dependency-free WSGI review adapter."""
import io
import json
import unittest
from unittest.mock import Mock

from ecmwf_collector.review_api import ReviewWsgiApplication
from ecmwf_collector.review_service import AuthenticatedActor


class IdentityProvider:
    def current_actor(self):
        return AuthenticatedActor("reviewer-1", "reviewer")


class ReviewWsgiApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = Mock()
        self.app = ReviewWsgiApplication(
            self.repository, lambda environ: IdentityProvider()
        )

    def request(self, method, path, payload=None, query=""):
        body = json.dumps(payload or {}).encode("utf-8")
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": io.BytesIO(body),
        }
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)
        response = b"".join(self.app(environ, start_response))
        return captured, json.loads(response.decode("utf-8"))

    def test_mutation_rejects_client_supplied_role_and_identity(self):
        response, payload = self.request(
            "POST", "/api/v1/reviews/r1/open",
            {"expected_version": 2, "role": "admin", "actor_id": "attacker"},
        )
        self.assertTrue(response["status"].startswith("400"))
        self.assertEqual(payload["error"], "invalid_request")
        self.repository.transition.assert_not_called()

    def test_decision_does_not_accept_client_quality_status(self):
        response, payload = self.request(
            "POST", "/api/v1/reviews/r1/decision",
            {"expected_version": 3, "decision": "approved",
             "reason": "Reviewed", "quality_status": "passed"},
        )
        self.assertTrue(response["status"].startswith("400"))
        self.repository.transition.assert_not_called()

    def test_open_passes_only_expected_version_and_domain_payload(self):
        from ecmwf_collector.review_workflow import ReviewCase
        self.repository.transition.return_value = ReviewCase("r1", 5, status="in_review")
        response, payload = self.request(
            "POST", "/api/v1/reviews/r1/open", {"expected_version": 2}
        )
        self.assertTrue(response["status"].startswith("200"))
        self.repository.transition.assert_called_once_with(
            "r1", operation="open", actor_id="reviewer-1",
            role="reviewer", expected_version=2,
        )
        self.assertEqual(payload["status"], "in_review")
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")

    def test_body_size_is_limited(self):
        body = b"{}"
        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/api/v1/reviews/r1/open",
            "CONTENT_LENGTH": "1048577",
            "wsgi.input": io.BytesIO(body),
        }
        captured = {}
        response = b"".join(self.app(environ, lambda status, headers: captured.update(status=status)))
        self.assertTrue(captured["status"].startswith("400"))
        self.assertIn(b"1 MiB", response)


if __name__ == "__main__":
    unittest.main()
