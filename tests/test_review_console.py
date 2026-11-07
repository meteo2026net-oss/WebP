import unittest
from unittest.mock import patch, Mock

from ecmwf_collector.gui.review_console import OidcPkceLogin, ReviewApiClient, ReviewAuthError


class ReviewConsoleAuthTests(unittest.TestCase):
    def test_oidc_scope_does_not_request_offline_access(self):
        self.assertEqual(OidcPkceLogin("https://id.example.test", "desktop-client").scopes,
                         "openid profile")

    def test_callback_server_binds_loopback_and_expected_path(self):
        server, received, ready, redirect_uri = OidcPkceLogin._callback_server()
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertTrue(redirect_uri.startswith("http://127.0.0.1:"))
            self.assertTrue(redirect_uri.endswith("/oidc/callback"))
        finally:
            server.server_close()

    def test_api_client_rejects_non_tls_remote_endpoint(self):
        with self.assertRaises(ValueError):
            ReviewApiClient("http://review.example.test", "temporary-token")

    def test_api_client_allows_local_development_and_sends_bearer_in_memory(self):
        client = ReviewApiClient("http://127.0.0.1:8080", "temporary-token")
        response = Mock()
        response.ok = True
        response.json.return_value = {"items": []}
        with patch("ecmwf_collector.gui.review_console.requests.request",
                   return_value=response) as request:
            self.assertEqual(client.request("GET", "/api/v1/reviews")["items"], [])
        self.assertEqual(
            request.call_args.kwargs["headers"]["Authorization"],
            "Bearer temporary-token",
        )
        client.clear()
        self.assertEqual(client._access_token, "")

    def test_401_requires_fresh_login_instead_of_refresh_token(self):
        client = ReviewApiClient("https://review.example.test", "short-lived")
        response = Mock()
        response.status_code = 401
        response.ok = False
        with patch("ecmwf_collector.gui.review_console.requests.request",
                   return_value=response):
            with self.assertRaisesRegex(ReviewAuthError, "سجّل الدخول مجدداً"):
                client.request("GET", "/api/v1/reviews")


if __name__ == "__main__":
    unittest.main()
