import unittest

from ecmwf_collector.oidc_identity import OIDCSettings
from ecmwf_collector.postgres_review_runtime import create_review_runtime


class ReviewRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.oidc = OIDCSettings(
            issuer="https://id.example.test/",
            audience="review-api",
            jwks_url="https://id.example.test/jwks",
            role_claim="review_role",
            role_mapping={"wx-reviewer": "reviewer"},
        )

    def test_rejects_database_connection_without_verified_tls(self):
        with self.assertRaisesRegex(ValueError, "sslmode=verify-full"):
            create_review_runtime(
                dsn="host=db.example.test dbname=weather user=review_api sslmode=require",
                oidc_settings=self.oidc,
            )

    def test_rejects_dsn_without_explicit_host(self):
        with self.assertRaisesRegex(ValueError, "must specify a database host"):
            create_review_runtime(
                dsn="dbname=weather user=review_api sslmode=verify-full",
                oidc_settings=self.oidc,
            )


if __name__ == "__main__":
    unittest.main()
