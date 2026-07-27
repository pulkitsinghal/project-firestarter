import {
  createRemoteJWKSet,
  jwtVerify,
} from "jose";

import {
  createSession,
  deriveIdentityOwner,
  deriveIdentityRoom,
  readSessionId,
  serializeSessionCookie,
} from "./session.js";

function unauthorized(message = "Authentication is required.") {
  const error = new Error(message);
  error.statusCode = 401;
  error.authenticate = "Bearer";
  return error;
}

function bearerToken(header) {
  if (typeof header !== "string") {
    return null;
  }
  const match = /^Bearer ([A-Za-z0-9\-._~+/]+=*)$/.exec(header);
  if (!match || match[1].length > 8192) {
    return null;
  }
  return match[1];
}

function claimText(payload, name) {
  const value = payload[name];
  if (
    typeof value !== "string" ||
    !value ||
    value.length > 256
  ) {
    throw unauthorized("The access token is missing required identity claims.");
  }
  return value;
}

function claimExpiration(payload) {
  if (!Number.isInteger(payload.exp) || payload.exp <= 0) {
    throw unauthorized("The access token is missing a valid expiration.");
  }
  return payload.exp;
}

function identityFor(
  tenant,
  subject,
  sessionSecret,
  expiresAt = null,
) {
  return Object.freeze({
    ownerKey: deriveIdentityOwner(tenant, subject, sessionSecret),
    notificationRoom: deriveIdentityRoom(tenant, subject, sessionSecret),
    expiresAt,
  });
}

export function createOidcTokenVerifier({
  issuer,
  audience,
  jwksUrl = null,
  algorithms = ["RS256"],
  tenantClaim = "tenant_id",
  keySet = null,
}) {
  const jwks = keySet ?? createRemoteJWKSet(new URL(jwksUrl));
  return (token) =>
    jwtVerify(token, jwks, {
      issuer,
      audience,
      algorithms,
      requiredClaims: ["sub", tenantClaim, "exp"],
    });
}

export function createIdentityService({
  authMode = "anonymous",
  sessionSecret,
  taskRetentionSeconds = 24 * 60 * 60,
  secureCookies = false,
  oidcIssuer = null,
  oidcAudience = null,
  oidcJwksUrl = null,
  oidcAlgorithms = ["RS256"],
  oidcTenantClaim = "tenant_id",
  tokenVerifier = null,
}) {
  const verifyToken =
    authMode === "oidc"
      ? tokenVerifier ??
        createOidcTokenVerifier({
          issuer: oidcIssuer,
          audience: oidcAudience,
          jwksUrl: oidcJwksUrl,
          algorithms: oidcAlgorithms,
          tenantClaim: oidcTenantClaim,
        })
      : null;

  async function oidcIdentity(token) {
    if (!token) {
      throw unauthorized();
    }
    try {
      const { payload } = await verifyToken(token);
      return identityFor(
        claimText(payload, oidcTenantClaim),
        claimText(payload, "sub"),
        sessionSecret,
        claimExpiration(payload),
      );
    } catch (error) {
      if (error?.statusCode === 401) {
        throw error;
      }
      throw unauthorized("The access token is invalid or expired.");
    }
  }

  function anonymousIdentity(cookieHeader, response = null) {
    let sessionId = readSessionId(cookieHeader, sessionSecret);
    if (!sessionId) {
      if (!response) {
        throw unauthorized("A tutorial session is required.");
      }
      const session = createSession(sessionSecret);
      sessionId = session.sessionId;
      response.setHeader(
        "Set-Cookie",
        serializeSessionCookie(session.token, {
          secure: secureCookies,
          maxAgeSeconds: taskRetentionSeconds,
        }),
      );
    }
    return identityFor("local", sessionId, sessionSecret);
  }

  return Object.freeze({
    async authenticateRequest(request, response) {
      if (authMode === "oidc") {
        return oidcIdentity(bearerToken(request.headers.authorization));
      }
      return anonymousIdentity(request.headers.cookie, response);
    },
    async authenticateSocket(socket) {
      if (authMode === "oidc") {
        return oidcIdentity(socket.handshake.auth?.token);
      }
      return anonymousIdentity(socket.request.headers.cookie);
    },
  });
}
