#!/usr/bin/env node
// Email Flywheel — a dependency-free "growth loop" drop.
//
// Reads what actually shipped (merged PRs in the window), asks Claude to draft one
// short honest update email, and delivers it. No `npm install`: it uses Node 20's
// built-in global `fetch` plus the stdlib `node:net`/`node:tls` for SMTP. It runs
// in GitHub Actions where ANTHROPIC_API_KEY, GITHUB_TOKEN and GITHUB_REPOSITORY are
// already present (see .github/workflows/email-flywheel.yml).
//
// Safe by default: with no SMTP_HOST / FLYWHEEL_RECIPIENTS it only *drafts* the
// email and writes a preview to the Actions run summary — a dry run, nothing sent.
// Sending turns on only when the operator wires their OWN mailbox (no third-party
// subscription), mirroring the auth add-on's delivery philosophy.
//
// Customize it by editing `.github/agent/email-flywheel.prompt.md`.

import { readFile } from "node:fs/promises";
import { appendFileSync } from "node:fs";
import net from "node:net";
import tls from "node:tls";
import os from "node:os";

const {
  ANTHROPIC_API_KEY,
  GITHUB_TOKEN,
  GITHUB_REPOSITORY,
  MODEL = "{{ claude_model }}",
  AGENT_PROMPT_FILE = ".github/agent/email-flywheel.prompt.md",
  FLYWHEEL_WINDOW_DAYS,
  FLYWHEEL_RECIPIENTS,
  SMTP_HOST,
  SMTP_PORT,
  SMTP_USERNAME,
  SMTP_PASSWORD,
  SMTP_SENDER,
} = process.env;

function requireEnv(name, value) {
  if (!value) {
    console.error(`✗ ${name} is required (set it as a repo secret / it is provided by Actions).`);
    process.exit(1);
  }
}
requireEnv("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY);
requireEnv("GITHUB_TOKEN", GITHUB_TOKEN);
requireEnv("GITHUB_REPOSITORY", GITHUB_REPOSITORY);

const WINDOW_DAYS = Math.max(1, Number(FLYWHEEL_WINDOW_DAYS) || 7);

const FALLBACK_PROMPT =
  "You are the {{ project_name }} email flywheel. Turn the provided list of recently " +
  "merged pull requests into ONE short, warm, honest update email. First line = the " +
  "subject; the rest = the body (under ~180 words). Ground everything in the list; do " +
  "not invent features, dates, or links. End with one light call to action.";

async function loadPrompt() {
  try {
    const text = (await readFile(AGENT_PROMPT_FILE, "utf8")).trim();
    if (text) return text;
  } catch {
    /* no prompt file — fall back */
  }
  return FALLBACK_PROMPT;
}

// --- Flywheel fuel: what actually shipped -----------------------------------

async function recentlyMerged(days) {
  const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
  const q = encodeURIComponent(`repo:${GITHUB_REPOSITORY} is:pr is:merged merged:>=${since}`);
  const url = `https://api.github.com/search/issues?q=${q}&sort=updated&order=desc&per_page=30`;
  const res = await fetch(url, {
    headers: {
      authorization: `Bearer ${GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "user-agent": "{{ project_slug }}-email-flywheel",
    },
  });
  if (!res.ok) throw new Error(`GitHub API ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return (data.items || []).map((it) => ({ number: it.number, title: it.title }));
}

// --- Draft ------------------------------------------------------------------

async function askClaude(prompt) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 1024,
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!res.ok) throw new Error(`Anthropic API ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return (data.content || [])
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("\n")
    .trim();
}

function splitDraft(draft) {
  const nl = draft.indexOf("\n");
  let subject = (nl === -1 ? draft : draft.slice(0, nl)).trim();
  let body = (nl === -1 ? "" : draft.slice(nl + 1)).trim();
  subject = subject.replace(/^subject:\s*/i, "").trim();
  if (!subject) subject = "{{ project_name }} — what shipped recently";
  if (!body) body = draft.trim();
  return { subject, body };
}

// --- Delivery: minimal, dependency-free SMTP over the operator's own mailbox --
// Node has no stdlib SMTP client, so we speak just enough of the protocol over
// node:tls / node:net. TLS is verified (cert + hostname) so credentials are never
// exposed to a passive MITM — the same stance as the auth add-on's SmtpDeliverer.

function sanitizeHeader(value) {
  // Strip CR/LF to prevent header injection via a crafted subject/sender.
  return String(value).replace(/[\r\n]+/g, " ").trim();
}

function envelopeAddr(value) {
  const m = String(value).match(/<([^>]+)>/);
  return (m ? m[1] : value).trim();
}

function buildMessage({ from, to, subject, text }) {
  const headers = [
    `From: ${sanitizeHeader(from)}`,
    `To: ${to.map(sanitizeHeader).join(", ")}`,
    `Subject: ${sanitizeHeader(subject)}`,
    `Date: ${new Date().toUTCString()}`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
    "Content-Transfer-Encoding: 8bit",
  ].join("\r\n");
  // Normalize to CRLF and dot-stuff any line beginning with "." (SMTP DATA rule).
  const body = String(text).replace(/\r?\n/g, "\r\n").replace(/^\./gm, "..");
  return `${headers}\r\n\r\n${body}`;
}

// Reads complete SMTP replies (handles multi-line 250-… continuations) off a socket.
function attachReader(socket) {
  const state = { buf: "", pending: null, error: null };
  const tryResolve = () => {
    if (!state.pending) return;
    if (state.error) {
      const p = state.pending;
      state.pending = null;
      p.reject(state.error);
      return;
    }
    const lines = state.buf.split("\n");
    let consumed = 0;
    for (let i = 0; i < lines.length; i++) {
      const terminated = i < lines.length - 1;
      consumed += lines[i].length + (terminated ? 1 : 0);
      // A reply is complete at the first terminated line of the form "NNN " (space,
      // not the "NNN-" continuation marker).
      if (terminated && /^\d{3} /.test(lines[i])) {
        const raw = state.buf.slice(0, consumed);
        state.buf = state.buf.slice(consumed);
        const p = state.pending;
        state.pending = null;
        p.resolve({ code: Number(raw.slice(0, 3)), text: raw.trim() });
        return;
      }
    }
  };
  socket.on("data", (d) => {
    state.buf += d.toString("utf8");
    tryResolve();
  });
  socket.on("error", (e) => {
    state.error = e;
    tryResolve();
  });
  socket.on("close", () => {
    if (state.pending && !state.error) {
      const p = state.pending;
      state.pending = null;
      p.reject(new Error("SMTP connection closed unexpectedly"));
    }
  });
  return () =>
    new Promise((resolve, reject) => {
      state.pending = { resolve, reject };
      tryResolve();
    });
}

async function smtpSend({ host, port, username, password }, { from, to, subject, text }) {
  const implicitTls = port === 465;
  const connect = (factory) =>
    new Promise((resolve, reject) => {
      const s = factory(() => resolve(s));
      s.setTimeout(20000, () => s.destroy(new Error("SMTP timeout")));
      s.once("error", reject);
    });

  let socket = await connect((ready) =>
    implicitTls
      ? tls.connect({ host, port, servername: host }, ready)
      : net.connect({ host, port }, ready),
  );
  let readReply = attachReader(socket);
  const ehloName = os.hostname() || "localhost";

  const expect = async (okCodes, label) => {
    const r = await readReply();
    if (!okCodes.includes(r.code)) throw new Error(`SMTP ${label} failed: ${r.text}`);
    return r;
  };
  const send = (line) =>
    new Promise((res, rej) => socket.write(`${line}\r\n`, (e) => (e ? rej(e) : res())));

  try {
    await expect([220], "greeting");
    await send(`EHLO ${ehloName}`);
    await expect([250], "EHLO");

    if (!implicitTls) {
      // Upgrade the plaintext connection before sending credentials.
      await send("STARTTLS");
      await expect([220], "STARTTLS");
      socket = await new Promise((resolve, reject) => {
        const t = tls.connect({ socket, servername: host }, () => resolve(t));
        t.setTimeout(20000, () => t.destroy(new Error("SMTP timeout")));
        t.once("error", reject);
      });
      readReply = attachReader(socket);
      await send(`EHLO ${ehloName}`);
      await expect([250], "EHLO (TLS)");
    }

    if (username) {
      await send("AUTH LOGIN");
      await expect([334], "AUTH LOGIN");
      await send(Buffer.from(username).toString("base64"));
      await expect([334], "AUTH username");
      await send(Buffer.from(password || "").toString("base64"));
      await expect([235], "AUTH password");
    }

    await send(`MAIL FROM:<${envelopeAddr(from)}>`);
    await expect([250], "MAIL FROM");
    for (const rcpt of to) {
      await send(`RCPT TO:<${envelopeAddr(rcpt)}>`);
      await expect([250, 251], `RCPT TO ${rcpt}`);
    }
    await send("DATA");
    await expect([354], "DATA");
    socket.write(`${buildMessage({ from, to, subject, text })}\r\n.\r\n`);
    await expect([250], "message body");
    await send("QUIT");
  } finally {
    socket.end();
  }
}

// --- Preview surface --------------------------------------------------------

function writeSummary({ subject, body, shipped, sent, reason, recipients }) {
  const path = process.env.GITHUB_STEP_SUMMARY;
  if (!path) return;
  const status = sent
    ? `📧 **Sent** to ${recipients.length} recipient(s).`
    : `📝 **Dry run — not sent** (${reason}). Add your SMTP secrets and \`FLYWHEEL_RECIPIENTS\` to enable sending. See \`docs/EMAIL_FLYWHEEL.md\`.`;
  const md = [
    "## Email Flywheel",
    "",
    status,
    "",
    `Based on **${shipped.length}** merged PR(s) in the last **${WINDOW_DAYS}** day(s).`,
    "",
    `**Subject:** ${subject}`,
    "",
    "**Body:**",
    "",
    "```",
    body,
    "```",
    "",
  ].join("\n");
  try {
    appendFileSync(path, `${md}\n`);
  } catch {
    /* best-effort; never fail the run over the preview */
  }
}

// --- Main -------------------------------------------------------------------

const shipped = await recentlyMerged(WINDOW_DAYS);
const shippedList = shipped.length
  ? shipped.map((p) => `- #${p.number} ${p.title}`).join("\n")
  : "(nothing merged in this window)";

const draft = await askClaude(
  `${await loadPrompt()}\n\n---\nMerged in the last ${WINDOW_DAYS} day(s):\n${shippedList}`,
);
if (!draft) {
  console.error("✗ Empty response from the model; not drafting an email.");
  process.exit(1);
}
const { subject, body } = splitDraft(draft);

const recipients = (FLYWHEEL_RECIPIENTS || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const canSend = Boolean(SMTP_HOST) && recipients.length > 0;

if (!canSend) {
  const reason = !SMTP_HOST ? "no SMTP_HOST configured" : "no FLYWHEEL_RECIPIENTS configured";
  writeSummary({ subject, body, shipped, sent: false, reason, recipients });
  console.log(`✎ Dry run (${reason}). Drafted but did not send:\n\nSubject: ${subject}\n\n${body}`);
  process.exit(0);
}

const sender = SMTP_SENDER || SMTP_USERNAME;
if (!sender) {
  console.error("✗ Set SMTP_SENDER (or SMTP_USERNAME) as the From address to send.");
  process.exit(1);
}
await smtpSend(
  { host: SMTP_HOST, port: Number(SMTP_PORT) || 587, username: SMTP_USERNAME, password: SMTP_PASSWORD },
  { from: sender, to: recipients, subject, text: body },
);
writeSummary({ subject, body, shipped, sent: true, recipients });
console.log(`✓ Sent "${subject}" to ${recipients.length} recipient(s).`);
