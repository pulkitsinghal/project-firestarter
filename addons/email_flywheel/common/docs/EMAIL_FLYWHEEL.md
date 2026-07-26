# Email Flywheel add-on

An opt-in growth loop: a GitHub Actions workflow that, on a recurring routine (or
on demand), reads what actually shipped in this repo, has an AI agent draft one
short honest update **email**, and — once you've wired your own mailbox — sends it
to a stakeholder / subscriber list. Momentum → outbound update → engagement → more
momentum. It's the email sibling of the [Scheduled Agent](SCHEDULED_AGENT.md)
add-on, which drops a GitHub issue instead.

Enable it at stamp time:

```bash
./bin/firestart.sh --set include_email_flywheel=yes
```

## What you get

| File | Purpose |
|------|---------|
| `.github/workflows/email-flywheel.yml` | The workflow. `workflow_dispatch` by default; a commented-out `schedule` block turns it into the recurring routine. Least-privilege (`contents: read` — the dry-run preview goes to the run summary; sending talks to your SMTP server, not the GitHub API). |
| `scripts/email-flywheel.mjs` | Dependency-free Node 20 script (global `fetch`, stdlib `node:net`/`node:tls` — no `npm install`): lists merged PRs in the window → asks the Anthropic Messages API to draft the email → **dry-runs** (preview only) or sends via your SMTP. |
| `.github/agent/email-flywheel.prompt.md` | The agent's instructions. Edit this to shape the voice and content of the update. |

## Setup

1. Add the API key secret (same one the AI PR reviewer uses):
   ```bash
   gh secret set ANTHROPIC_API_KEY
   ```
2. (Optional) pin the model with a repo variable, else it uses the stamped default:
   ```bash
   gh variable set CLAUDE_MODEL --body "{{ claude_model }}"
   ```
3. Run it once from the **Actions** tab → *Email Flywheel* → *Run workflow*. With no
   mail secrets set it does a **dry run**: it drafts the email and writes a preview
   to the run summary — nothing is sent.
4. To actually send, wire your **own** mailbox (no third-party subscription — this
   uses plain SMTP, the same stance as the `auth` add-on):
   ```bash
   gh variable set FLYWHEEL_RECIPIENTS --body "you@example.com,teammate@example.com"
   gh secret   set SMTP_HOST        # e.g. smtp.fastmail.com
   gh variable set SMTP_PORT --body 587   # 587 = STARTTLS (default), 465 = implicit TLS
   gh secret   set SMTP_USERNAME
   gh secret   set SMTP_PASSWORD
   gh variable set SMTP_SENDER --body "{{ project_name }} <you@example.com>"
   ```
5. (Optional) widen or narrow the look-back window (default 7 days):
   ```bash
   gh variable set FLYWHEEL_WINDOW_DAYS --body 14
   ```
6. To make it recurring, uncomment the `schedule:` cron in the workflow. **Each run
   costs a small API charge** (and sends real email once configured), which is why
   it ships OFF.

## Cost & safety

- **Nothing is sent until you opt in.** No `SMTP_HOST` or no `FLYWHEEL_RECIPIENTS`
  → dry run (draft + preview only). This makes it useful and safe before you point
  it at real inboxes.
- It is **read-only** on the repo (`contents: read` + `pull-requests: read` to list
  merged PRs); it never opens issues or PRs, and needs no write scope.
- Email goes through **your** SMTP server over verified TLS (cert + hostname), so
  credentials and content aren't exposed to a passive MITM. No SendGrid/Mailgun
  account, no new dependency, no host toolchain — it runs entirely on the runner.
- The draft is grounded in real merged PRs; the prompt tells the model not to
  invent features, dates, or links. Review the first few runs before enabling the
  recurring schedule.
