"""Contract for the public / unlisted / authenticated-review publishing posture."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "template" / "docs" / "UNLISTED_PUBLISHING.md"
EXAMPLE = (
    ROOT / "addons" / "convergent_deploy" / "common" / "docs" / "examples"
    / "unlisted-site"
)


class PublishingPosture(unittest.TestCase):
    def test_universal_doc_names_all_three_postures(self):
        text = DOC.read_text()
        for phrase in ("Public", "Unlisted", "Authenticated review"):
            self.assertIn(phrase, text)
        self.assertIn("Noindex is not access control", text)

    def test_copy_ready_static_pair_is_complete(self):
        headers = (EXAMPLE / "_headers").read_text()
        robots = (EXAMPLE / "robots.txt").read_text()
        for header in ("X-Robots-Tag", "Referrer-Policy", "X-Content-Type-Options"):
            self.assertIn(header, headers)
        self.assertIn("noindex", headers)
        self.assertEqual(robots, "User-agent: *\nDisallow: /\n")

    def test_otp_is_narrowed_by_audience_not_used_as_allow_everyone(self):
        text = DOC.read_text()
        self.assertIn("approved emails or approved domains", text)
        self.assertIn("admits any user with a valid email address", text)
        self.assertIn("Service Auth", text)
        self.assertIn("deny-by-default", text)
        self.assertIn("identity provider with MFA", text)
        self.assertIn("authenticated review responses too", text)

    def test_template_contains_no_source_specific_or_secret_material(self):
        text = "\n".join(
            path.read_text()
            for path in (DOC, EXAMPLE / "_headers", EXAMPLE / "robots.txt")
        ).lower()
        for forbidden in (
            "auggiehealth", "west nile", "wnv", "share-desk", "research-wnv-site",
            "cf-access-client-secret:", "cloudflare_account_id=", "@example.com",
        ):
            self.assertNotIn(forbidden, text)

    def test_existing_policy_and_security_doc_point_to_the_posture(self):
        self.assertIn(
            "UNLISTED_PUBLISHING.md",
            (ROOT / "template" / "docs" / "DEPLOY_POLICY.md").read_text(),
        )
        self.assertIn(
            "UNLISTED_PUBLISHING.md",
            (ROOT / "template" / "SECURITY.md").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
