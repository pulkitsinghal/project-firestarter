"""Contract: the auth add-on never gates a request on an Origin/Referer header,
and keeps the session credential a bearer token rather than an ambient cookie.

Lift of the share-desk lesson (issue #179). An Origin or Referer header is a
hint, not a credential: real mobile network paths (carrier proxies, in-app
browsers, privacy intermediaries) strip those headers on same-origin POSTs, so a
same-origin check built on them fails closed against your own users on cellular
while stopping no attacker, and the breakage only reproduces on a real cellular
path so it survives every desktop and CI run.

The add-on is already on the safe side, so the lift is this guard rather than a
new mechanism. The session credential is a bearer token kept in localStorage and
sent as X-Session-Token / Authorization, never a Set-Cookie, and the backend
adds no permissive CORS. A credential the browser does not attach automatically
to a cross-site request is not reachable by a forging page, so classic CSRF does
not apply and no CSRF token is needed. The static form of the issue's key
assertion ("a POST with no Origin header still succeeds") is this: nothing in the
route path refuses on Origin/Referer, so a request carrying neither is accepted
on its bearer token alone.

This test fails the moment someone "hardens" the routes with an Origin/Referer
same-origin check (the mobile-breaking fix) or moves the session onto an
unguarded cookie. If the session is ever moved to a cookie deliberately, replace
the cookie assertion with a sealed double-submit CSRF-token check, never an
Origin check.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "addons" / "auth" / "fastapi-next"
ROUTES = AUTH / "backend" / "app" / "api" / "auth_routes.py"
MAIN = AUTH / "backend" / "app" / "main.py"
WIDGET = AUTH / "frontend" / "app" / "auth-widget.tsx"
AUTH_DOC = AUTH / "docs" / "AUTH.md"
SECURITY = ROOT / "template" / "SECURITY.md"

# A code read of the Origin/Referer request header, in Python or TS:
#   request.headers.get("origin") / headers["Referer"] / req.headers.get('referer')
_HEADER_ORIGIN = re.compile(r"""headers?\s*(?:\.get\(|\[)\s*["']?(?:origin|referer)""", re.I)
# A same-origin gate helper call, e.g. is_same_origin(request) / sameOrigin(req):
_SAME_ORIGIN_CALL = re.compile(r"same[_-]?origin\s*\(", re.I)


class AuthRequestAuthenticityContract(unittest.TestCase):
    def setUp(self) -> None:
        missing = [p for p in (ROUTES, MAIN, WIDGET, AUTH_DOC, SECURITY) if not p.is_file()]
        self.assertFalse(
            missing,
            "auth add-on layout moved; update this contract: "
            + ", ".join(str(p.relative_to(ROOT)) for p in missing),
        )
        self.routes = ROUTES.read_text()
        self.main = MAIN.read_text()
        self.widget = WIDGET.read_text()
        self.auth_doc = AUTH_DOC.read_text()
        self.security = SECURITY.read_text()

    def test_mutating_routes_never_gate_on_an_origin_or_referer_header(self) -> None:
        for blob, where in ((self.routes, "backend auth_routes.py"), (self.main, "backend main.py")):
            self.assertIsNone(
                _HEADER_ORIGIN.search(blob),
                f"{where} reads an Origin/Referer header. Do not gate a request on it: "
                "those headers are stripped on real mobile network paths, so the check "
                "403s your own users on cellular and stops no attacker (#179).",
            )
            self.assertIsNone(
                _SAME_ORIGIN_CALL.search(blob),
                f"{where} calls a same-origin gate. Authenticate by a credential the "
                "forging site cannot supply, not by the request's origin (#179).",
            )

    def test_session_credential_is_a_bearer_token_not_an_ambient_cookie(self) -> None:
        # A cookie is the ambient authority CSRF rides; this add-on uses none.
        self.assertNotIn(
            "set_cookie",
            self.routes.lower(),
            "auth routes set a cookie. A cookie session is ambient authority: if intended, "
            "add a sealed double-submit CSRF token and update this contract (#179).",
        )
        # The credential travels as an explicit header the page must attach itself.
        self.assertTrue(
            "x_session_token" in self.routes.lower()
            or "x-session-token" in self.routes.lower()
            or "authorization" in self.routes.lower(),
            "auth routes no longer read a bearer-token header (#179).",
        )
        self.assertIn(
            "X-Session-Token", self.widget, "widget must send the bearer token as a header (#179)."
        )
        self.assertIn(
            "localStorage", self.widget, "widget must hold the token in localStorage, not a cookie (#179)."
        )

    def test_cors_is_not_opened_to_any_origin_with_credentials(self) -> None:
        # No CORS middleware ships today; if one is ever added it must not pair a
        # wildcard origin with credentials, which re-opens the cross-site surface.
        if "corsmiddleware" in self.main.lower():
            wildcard = re.search(r"""allow_origins\s*=\s*\[[^\]]*["']\*["']""", self.main)
            creds = re.search(r"allow_credentials\s*=\s*True", self.main)
            self.assertFalse(
                bool(wildcard and creds),
                "CORS allows any origin with credentials, which re-opens the CSRF surface (#179).",
            )

    def test_auth_doc_explains_the_request_authenticity_posture(self) -> None:
        low = self.auth_doc.lower()
        self.assertIn("csrf", low, "AUTH.md must document the CSRF/request-authenticity posture (#179).")
        self.assertIn("origin", low, "AUTH.md must name the Origin-header lesson (#179).")
        self.assertIn("mobile", low, "AUTH.md must record that the broken check fails on mobile (#179).")

    def test_security_md_states_the_generic_origin_is_not_a_credential_rule(self) -> None:
        low = self.security.lower()
        self.assertIn("origin", low, "SECURITY.md must carry the generic Origin-header rule (#179).")
        self.assertTrue(
            "hint" in low or "not a credential" in low,
            "SECURITY.md must state that an Origin/Referer header is a hint, not a credential (#179).",
        )


if __name__ == "__main__":
    unittest.main()
