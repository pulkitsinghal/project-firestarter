import assert from "node:assert/strict";
import test from "node:test";

import {
  createSession,
  deriveIdentityOwner,
  deriveNotificationRoom,
  readSessionId,
  serializeSessionCookie,
  signSessionId,
  verifySessionToken,
} from "../../src/session.js";

const SECRET = "unit-test-secret-that-is-at-least-32-bytes";

test("signed sessions round-trip and reject tampering", () => {
  const { sessionId, token } = createSession(SECRET);

  assert.equal(verifySessionToken(token, SECRET), sessionId);
  assert.equal(
    verifySessionToken(`${token.slice(0, -1)}x`, SECRET),
    null,
  );
  assert.equal(verifySessionToken(token, `${SECRET}-wrong`), null);
});

test("session cookies are HttpOnly, same-site, and secure in production", () => {
  const token = signSessionId("a".repeat(43), SECRET);
  const localCookie = serializeSessionCookie(token, { secure: false });
  const secureCookie = serializeSessionCookie(token, { secure: true });

  assert.match(localCookie, /HttpOnly/);
  assert.match(localCookie, /SameSite=Strict/);
  assert.doesNotMatch(localCookie, /; Secure/);
  assert.match(secureCookie, /; Secure/);
});

test("cookie parsing and room derivation do not expose socket IDs", () => {
  const { sessionId, token } = createSession(SECRET);
  assert.equal(
    readSessionId(`unrelated=value; {{ project_slug }}_session=${token}`, SECRET),
    sessionId,
  );

  const room = deriveNotificationRoom(sessionId, SECRET);
  assert.match(room, /^identity:[A-Za-z0-9_-]{43}$/);
  assert.doesNotMatch(room, new RegExp(sessionId));
});

test("tenant and subject derive stable, isolated owner keys", () => {
  const first = deriveIdentityOwner("tenant-a", "user-1", SECRET);
  assert.equal(
    first,
    deriveIdentityOwner("tenant-a", "user-1", SECRET),
  );
  assert.notEqual(
    first,
    deriveIdentityOwner("tenant-b", "user-1", SECRET),
  );
  assert.notEqual(
    first,
    deriveIdentityOwner("tenant-a", "user-2", SECRET),
  );
});
