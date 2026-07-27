import {
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";

export const SESSION_COOKIE_NAME = "{{ project_slug }}_session";

function hmac(value, secret) {
  return createHmac("sha256", secret).update(value).digest("base64url");
}

function parseCookies(header = "") {
  return Object.fromEntries(
    header
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const separator = part.indexOf("=");
        if (separator === -1) {
          return [part, ""];
        }
        return [part.slice(0, separator), part.slice(separator + 1)];
      }),
  );
}

function constantTimeEqual(left, right) {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return (
    leftBuffer.length === rightBuffer.length &&
    timingSafeEqual(leftBuffer, rightBuffer)
  );
}

export function signSessionId(sessionId, secret) {
  return `${sessionId}.${hmac(`session:${sessionId}`, secret)}`;
}

export function verifySessionToken(token, secret) {
  if (typeof token !== "string") {
    return null;
  }

  const separator = token.indexOf(".");
  if (separator < 1 || separator !== token.lastIndexOf(".")) {
    return null;
  }

  const sessionId = token.slice(0, separator);
  const signature = token.slice(separator + 1);
  if (
    !/^[A-Za-z0-9_-]{43}$/.test(sessionId) ||
    !/^[A-Za-z0-9_-]{43}$/.test(signature)
  ) {
    return null;
  }

  const expected = hmac(`session:${sessionId}`, secret);
  return constantTimeEqual(signature, expected) ? sessionId : null;
}

export function readSessionId(cookieHeader, secret) {
  return verifySessionToken(
    parseCookies(cookieHeader)[SESSION_COOKIE_NAME],
    secret,
  );
}

export function createSession(secret) {
  const sessionId = randomBytes(32).toString("base64url");
  return {
    sessionId,
    token: signSessionId(sessionId, secret),
  };
}

export function deriveNotificationRoom(sessionId, secret) {
  return deriveIdentityRoom("local", sessionId, secret);
}

export function deriveIdentityOwner(tenant, subject, secret) {
  return hmac(`owner:${tenant}\0${subject}`, secret);
}

export function deriveIdentityRoom(tenant, subject, secret) {
  return `identity:${hmac(`room:${tenant}\0${subject}`, secret)}`;
}

export function serializeSessionCookie(
  token,
  {
    secure,
    maxAgeSeconds = 24 * 60 * 60,
  },
) {
  const attributes = [
    `${SESSION_COOKIE_NAME}=${token}`,
    "Path=/",
    `Max-Age=${maxAgeSeconds}`,
    "HttpOnly",
    "SameSite=Strict",
  ];
  if (secure) {
    attributes.push("Secure");
  }
  return attributes.join("; ");
}
