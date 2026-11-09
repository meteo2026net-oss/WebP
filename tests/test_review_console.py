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
        response.is_redirect = False
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
        response.is_redirect = False
        with patch("ecmwf_collector.gui.review_console.requests.request",
                   return_value=response):
            with self.assertRaisesRegex(ReviewAuthError, "سجّل الدخول مجدداً"):
                client.request("GET", "/api/v1/reviews")


    def _metadata(self, issuer="https://id.example.test/realms/weather-review"):
        return {
            "issuer": issuer,
            "authorization_endpoint": issuer + "/protocol/openid-connect/auth",
            "token_endpoint": issuer + "/protocol/openid-connect/token",
            "jwks_uri": issuer + "/protocol/openid-connect/certs",
        }

    def test_trusted_tunnel_keeps_official_browser_authorization_endpoint(self):
        login = OidcPkceLogin(
            "https://id.example.test/realms/weather-review",
            "desktop-client",
            local_tunnel_url="http://127.0.0.1:8081",
        )
        endpoints = login._endpoint_urls(self._metadata())
        self.assertEqual(
            endpoints["authorization_endpoint"],
            "https://id.example.test/realms/weather-review/protocol/openid-connect/auth",
        )
        self.assertEqual(
            endpoints["token_endpoint"],
            "http://127.0.0.1:8081/realms/weather-review/protocol/openid-connect/token",
        )
        self.assertEqual(
            endpoints["jwks_uri"],
            "http://127.0.0.1:8081/realms/weather-review/protocol/openid-connect/certs",
        )
        self.assertEqual(
            login._discovery_url(),
            "http://127.0.0.1:8081/realms/weather-review/.well-known/openid-configuration",
        )

    def test_issuer_allows_only_trailing_slash_normalization(self):
        login = OidcPkceLogin(
            "https://id.example.test/realms/weather-review/",
            "desktop-client",
            local_tunnel_url="http://127.0.0.1:8081",
        )
        endpoints = login._endpoint_urls(self._metadata())
        self.assertTrue(endpoints["authorization_endpoint"].startswith("https://"))
        metadata = self._metadata(issuer="https://id.example.test/realms/other")
        with self.assertRaisesRegex(ReviewAuthError, "issuer"):
            login._endpoint_urls(metadata)

    def test_tunnel_rejects_non_loopback_and_non_http_targets(self):
        for tunnel in (
            "http://localhost:8081",
            "http://192.0.2.10:8081",
            "https://127.0.0.1:8081",
            "http://127.0.0.1:8082",
            "http://127.0.0.1:8081/other",
            "http://user@127.0.0.1:8081",
        ):
            with self.subTest(tunnel=tunnel):
                login = OidcPkceLogin(
                    "https://id.example.test/realms/weather-review",
                    "desktop-client",
                    local_tunnel_url=tunnel,
                )
                with self.assertRaises(ReviewAuthError):
                    login._discovery_url()

    def test_metadata_cannot_redirect_token_or_jwks_to_untrusted_host(self):
        login = OidcPkceLogin(
            "https://id.example.test/realms/weather-review",
            "desktop-client",
            local_tunnel_url="http://127.0.0.1:8081",
        )
        metadata = self._metadata()
        metadata["token_endpoint"] = "https://attacker.example/token"
        with self.assertRaisesRegex(ReviewAuthError, "token_endpoint"):
            login._endpoint_urls(metadata)
        metadata = self._metadata()
        metadata["jwks_uri"] = "http://127.0.0.1:8081/attacker-keys"
        with self.assertRaisesRegex(ReviewAuthError, "jwks_uri"):
            login._endpoint_urls(metadata)

    def test_discovery_url_is_loopback_only_when_tunnel_is_configured(self):
        login = OidcPkceLogin(
            "https://id.example.test/realms/weather-review", "desktop-client"
        )
        self.assertEqual(
            login._discovery_url(),
            "https://id.example.test/realms/weather-review/.well-known/openid-configuration",
        )


    def test_api_redirect_is_rejected_without_following_it(self):
        client = ReviewApiClient("http://127.0.0.1:8000", "temporary-token")
        response = Mock()
        response.is_redirect = True
        with patch("ecmwf_collector.gui.review_console.requests.request",
                   return_value=response) as request:
            with self.assertRaisesRegex(ReviewAuthError, "redirect"):
                client.request("GET", "/api/v1/reviews")
        self.assertFalse(request.call_args.kwargs.get("allow_redirects", True))


if __name__ == "__main__":
    unittest.main()
