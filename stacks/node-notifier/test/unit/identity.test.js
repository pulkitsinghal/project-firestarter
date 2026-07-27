import assert from "node:assert/strict";
import test from "node:test";

import {
  createLocalJWKSet,
  exportJWK,
  generateKeyPair,
  SignJWT,
} from "jose";

import {
  createIdentityService,
  createOidcTokenVerifier,
} from "../../src/identity.js";

const SECRET = "identity-test-secret-that-is-at-least-32-bytes";

test("anonymous identity persists through the signed tutorial cookie", async () => {
  let cookie;
  const identities = createIdentityService({
    authMode: "anonymous",
    sessionSecret: SECRET,
    taskRetentionSeconds: 600,
  });
  const first = await identities.authenticateRequest(
    { headers: {} },
    {
      setHeader(name, value) {
        assert.equal(name, "Set-Cookie");
        cookie = value.split(";", 1)[0];
      },
    },
  );
  const second = await identities.authenticateSocket({
    request: { headers: { cookie } },
    handshake: {},
  });

  assert.equal(first.ownerKey, second.ownerKey);
  assert.equal(first.notificationRoom, second.notificationRoom);
  assert.doesNotMatch(cookie, new RegExp(first.ownerKey));
});

test("OIDC identity is stable across tokens and isolated by tenant", async () => {
  const identities = createIdentityService({
    authMode: "oidc",
    sessionSecret: SECRET,
    oidcTenantClaim: "tenant_id",
    tokenVerifier: async (token) => ({
      payload:
        token === "tenant-b"
          ? {
              sub: "user-1",
              tenant_id: "tenant-b",
              exp: Math.floor(Date.now() / 1000) + 300,
            }
          : {
              sub: "user-1",
              tenant_id: "tenant-a",
              exp: Math.floor(Date.now() / 1000) + 300,
            },
    }),
  });
  const first = await identities.authenticateRequest(
    { headers: { authorization: "Bearer first-token" } },
    {},
  );
  const refreshed = await identities.authenticateSocket({
    request: { headers: {} },
    handshake: { auth: { token: "refreshed-token" } },
  });
  const otherTenant = await identities.authenticateRequest(
    { headers: { authorization: "Bearer tenant-b" } },
    {},
  );

  assert.equal(first.ownerKey, refreshed.ownerKey);
  assert.equal(first.notificationRoom, refreshed.notificationRoom);
  assert.notEqual(first.ownerKey, otherTenant.ownerKey);
  await assert.rejects(
    identities.authenticateRequest({ headers: {} }, {}),
    /Authentication is required/,
  );
});

test("OIDC failures are returned as generic authentication errors", async () => {
  const identities = createIdentityService({
    authMode: "oidc",
    sessionSecret: SECRET,
    tokenVerifier: async () => {
      throw new Error("provider-specific validation details");
    },
  });

  await assert.rejects(
    identities.authenticateRequest(
      { headers: { authorization: "Bearer invalid-token" } },
      {},
    ),
    (error) =>
      error.statusCode === 401 &&
      error.message === "The access token is invalid or expired.",
  );
});

test("OIDC verifier pins algorithm, issuer, audience, and identity claims", async () => {
  const { privateKey, publicKey } = await generateKeyPair("RS256");
  const publicJwk = await exportJWK(publicKey);
  publicJwk.kid = "test-key";
  publicJwk.alg = "RS256";
  const verifier = createOidcTokenVerifier({
    issuer: "https://identity.example/",
    audience: "notifier-api",
    algorithms: ["RS256"],
    tenantClaim: "tenant_id",
    keySet: createLocalJWKSet({ keys: [publicJwk] }),
  });
  const validToken = await new SignJWT({
    tenant_id: "tenant-a",
  })
    .setProtectedHeader({ alg: "RS256", kid: "test-key", typ: "at+jwt" })
    .setIssuer("https://identity.example/")
    .setAudience("notifier-api")
    .setSubject("user-1")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(privateKey);
  const wrongAudience = await new SignJWT({
    tenant_id: "tenant-a",
  })
    .setProtectedHeader({ alg: "RS256", kid: "test-key", typ: "at+jwt" })
    .setIssuer("https://identity.example/")
    .setAudience("another-api")
    .setSubject("user-1")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(privateKey);

  assert.equal((await verifier(validToken)).payload.sub, "user-1");
  await assert.rejects(verifier(wrongAudience), /aud/);
});
