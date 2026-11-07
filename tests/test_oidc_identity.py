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

    def test_requires_https_oidc_endpoints(self):
        with self.assertRaises(ValueError):
            OIDCSettings(
                issuer="http://identity.example.test",
                audience="api",
                jwks_url="https://identity.example.test/jwks",
                role_claim="role",
                role_mapping={"reviewer": "reviewer"},
            )


if __name__ == "__main__":
    unittest.main()
