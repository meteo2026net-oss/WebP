from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from ecmwf_collector.oidc_identity import OIDCIdentityProvider, OIDCSettings


class OIDCIdentityTests(unittest.TestCase):
    def setUp(self):
        self.settings = OIDCSettings(
            issuer="https://identity.example.test/",
            audience="weather-review-api",
            jwks_url="https://identity.example.test/.well-known/jwks.json",
            role_claim="review_role",
            role_mapping={"wx-reviewer": "reviewer", "wx-lead": "review_lead"},
        )

    def test_maps_only_server_configured_role_and_verified_subject(self):
        client = Mock()
        client.get_signing_key_from_jwt.return_value.key = object()
        claims = {"sub": "user-123", "review_role": "wx-lead"}
        with patch.dict("sys.modules", {"jwt": Mock(decode=Mock(return_value=claims))}):
            actor = OIDCIdentityProvider(
                {"HTTP_AUTHORIZATION": "Bearer eyJhbGciOiJSUzI1NiJ9.test.sig"},
                self.settings,
                jwks_client=client,
            ).current_actor()
        self.assertEqual(actor.subject, "user-123")
        self.assertEqual(actor.role, "review_lead")

    def test_rejects_missing_bearer_token(self):
        with self.assertRaises(PermissionError):
            OIDCIdentityProvider({}, self.settings, jwks_client=Mock()).current_actor()

    def test_rejects_unmapped_role(self):
        client = Mock()
        client.get_signing_key_from_jwt.return_value.key = object()
        claims = {"sub": "user-123", "review_role": "administrator"}
        with patch.dict("sys.modules", {"jwt": Mock(decode=Mock(return_value=claims))}):
            with self.assertRaises(PermissionError):
                OIDCIdentityProvider(
                    {"HTTP_AUTHORIZATION": "Bearer token"},
                    self.settings,
                    jwks_client=client,
                ).current_actor()

    def test_allows_loopback_http_for_jwks_only(self):
        settings = OIDCSettings(
            issuer="https://identity.example.test/realms/weather-review",
            audience="api",
            jwks_url="http://127.0.0.1:8081/realms/weather-review/certs",
            role_claim="role",
            role_mapping={"reviewer": "reviewer"},
        )
        self.assertEqual(settings.jwks_url, "http://127.0.0.1:8081/realms/weather-review/certs")

    def test_rejects_non_loopback_http_jwks(self):
        with self.assertRaises(ValueError):
            OIDCSettings(
                issuer="https://identity.example.test",
                audience="api",
                jwks_url="http://identity.example.test/jwks",
                role_claim="role",
                role_mapping={"reviewer": "reviewer"},
            )

    def test_requires_https_oidc_endpoints(self):
        with self.assertRaises(ValueError):
            OIDCSettings(
                issuer="http://identity.example.test",
                audience="api",
                jwks_url="https://identity.example.test/jwks",
                role_claim="role",
                role_mapping={"reviewer": "reviewer"},
            )


    def test_maps_all_four_review_roles_from_server_owned_allowlist(self):
        role_mapping = {
            "reviewer": "reviewer",
            "review_lead": "review_lead",
            "publisher": "publisher",
            "admin": "admin",
        }
        for claim_value, expected_role in role_mapping.items():
            with self.subTest(role=expected_role):
                client = Mock()
                client.get_signing_key_from_jwt.return_value.key = object()
                claims = {"sub": "test-" + expected_role, "review_role": claim_value}
                settings = OIDCSettings(
                    issuer="https://identity.example.test/realms/weather-review",
                    audience="review-api",
                    jwks_url="https://identity.example.test/realms/weather-review/certs",
                    role_claim="review_role",
                    role_mapping=role_mapping,
                )
                with patch.dict("sys.modules", {"jwt": Mock(decode=Mock(return_value=claims))}):
                    actor = OIDCIdentityProvider(
                        {"HTTP_AUTHORIZATION": "Bearer signed-token"},
                        settings,
                        jwks_client=client,
                    ).current_actor()
                self.assertEqual(actor.role, expected_role)
                self.assertEqual(actor.subject, "test-" + expected_role)


if __name__ == "__main__":
    unittest.main()
