# Doing real work while a secret value never touches the AI

An autonomous agent (or a scripted pipeline) can configure, deploy, and rotate a
secured service without ever holding a secret value. The trick is to **author
pipes where the plaintext flows from a vault straight to the consumer** and never
enters the model's context, a chat transcript, a command's arguments (`argv` is
world-readable through `ps`), shell history, a committed file, a log line, or a
screenshot. The agent writes the plumbing; the value only ever travels through
it.

This doc collects the reusable patterns. They are deliberately generic: swap your
own secret names, hosts, and job names for the `<placeholders>`. Nothing here
needs a real credential to read or to adopt.

Companion docs in this repo:

- [`addons/secret_vault`](../addons/secret_vault/README.md): a cross-platform,
  redundant local **vault** with fingerprint integrity and runtime injection.
  Its [`SECRETS.md`](../addons/secret_vault/common/docs/SECRETS.md) is the house
  contract; [`SECRET_VAULT.md`](../addons/secret_vault/common/docs/SECRET_VAULT.md)
  is the concept and usage. Use it for the **local** half: store once, stream
  into a consumer with `secret-get --exec`.
- The private overlay's `secret_injection` add-on: the **server** half, a
  vault-to-server pipe (`secret manager read | ssh ... write env ... recreate
  service`). Enabled only when you stamp with the private overlay.
- [`SECURE-REMOTE-ACCESS.md`](SECURE-REMOTE-ACCESS.md): hardening the host and
  keeping sign-in owner-held, which is where patterns 5 and 6 below live in full.

## The one rule, stated once

Plaintext may flow **vault -> anonymous pipe -> consumer**. It must never land in
any of these:

| Allowed to carry plaintext | Must never carry plaintext |
|----------------------------|----------------------------|
| an anonymous shell pipe (`\|`) | the model's context or any chat message |
| `stdin` of the consuming process | a command-line argument (`argv`, visible via `ps`) |
| a locked (`0600`) file, deleted after use | shell history (`~/.*_history`) |
| the child process's environment, set at `exec` | a committed file, a log, or a screenshot |
| | a URL or query string |

Everything below is a concrete way to keep plaintext on the left and off the
right. Only **non-secret metadata** (a sha256 fingerprint, a byte length, a
per-store status) is ever printed or returned.

## 1. Pipe, do not print

The primitive move is to read a secret and hand it to exactly one consumer over a
single pipe, so it is never materialized:

```bash
# good: the value crosses one anonymous pipe and is gone
secret-manager read <NAME> | <consumer> --stdin

# bad: the value is now in argv (ps), a variable, and probably history
<consumer> --key "$(secret-manager read <NAME>)"
```

For the local-vault version of this, `secret_vault`'s `secret-get <NAME> --exec
ENV -- <cmd>` sets the value in the child's environment only and then `exec`s, so
it is never in your shell, a file, or argv.

## 2. Vault-to-server pipe

Push a secret from a cloud secret manager straight into a remote service's
environment and restart it, without the value ever touching your laptop disk,
your history, or the agent:

```bash
secret-manager read <NAME> \
  | ssh <deploy-host> 'S=$(cat); umask 077
      cd <app-dir>
      grep -v "^<ENV_KEY>=" .env > .env.next 2>/dev/null || true
      printf "%s=%s\n" "<ENV_KEY>" "$S" >> .env.next
      mv .env.next .env
      <recreate-the-service>'
```

Why it is safe: the value is read on the remote side with `S=$(cat)` from
**stdin**; only the non-secret parameters (`<ENV_KEY>`, `<app-dir>`) are
interpolated locally; the value is never echoed and never an argument.

> **Gotcha that silently breaks it.** Do **not** feed the remote script with a
> here-doc or here-string (`ssh host <<'EOF' ... EOF`) on the *same* `ssh` that
> carries the secret pipe. The redirection overrides the pipe, `cat` reads the
> script instead of the secret, and the service comes up with an **empty**
> value. Pass the remote command as an `ssh` **argument** (as above) so `stdin`
> stays the piped secret.

Rotation needs no code change: services read their environment at boot, so
re-running the pipe with a new version and recreating the service is the whole
rotation. (`secret manager` here is whatever your provider ships, for example
`gcloud secrets versions access`, `aws secretsmanager get-secret-value`, or a
`secret-get` from the local vault.)

## 3. Seed once by a human, and why that step exists

A brand-new secret that only exists on a web page (a freshly minted API key, an
OAuth client secret shown once) has to enter the vault a first time. **This first
hop is a deliberate human step, by design:** the platform correctly blocks an AI
from scraping a secret value off a page, and that block is a feature, not an
obstacle.

```bash
# macOS: value comes from the OS clipboard, is never printed or passed as argv
pbpaste | secret-manager create <NAME> --data-file=-
```

After the value is in the vault, **every** inject, rotate, and deploy afterward
is fully autonomous with zero human secret handling. The single human touch is
the smallest possible trusted base: one copy, once, into the vault.

## 4. Browser clipboard bridge: capture a one-time web secret without reading it

When a secret is shown once in a browser and you want to avoid even eyeballing it,
you can still get it into the vault without the agent ever seeing the value.

- **Prefer the page's own copy control.** Click the site's "copy" button so the
  value goes to the OS clipboard; the agent never reads it.
- **Or run a tiny snippet that returns only a length,** never the value:

  ```js
  // writes the field value to the OS clipboard and returns ONLY its length
  const el = document.querySelector('<selector-for-the-secret-field>');
  const v = el.value ?? el.textContent ?? '';
  await navigator.clipboard.writeText(v);
  v.length;   // the only thing handed back to the caller
  ```

Then seed from the clipboard (pattern 3) and clear it immediately:

```bash
pbpaste | secret-manager create <NAME> --data-file=-
printf '' | pbcopy    # clear the clipboard so the value does not linger
```

Rules for this bridge:

- **Never screenshot or read the secret.** Verify success by its **length** and
  by a later successful *use* of the credential, not by printing the value.
- **Always dry-run the whole pipe with a DUMMY value first.** Prove the clipboard
  -> `create` -> clear chain works on throwaway data, so a bug surfaces there and
  not on the real one-time key you cannot see again.

## 5. Unattended auth: a least-privilege, job-owned service account

A scheduled job (`cron` / `launchd` / `systemd`) must not depend on an
interactive, browser-plus-2FA login, which will eventually expire and fail
mid-run. The fix is **not** to weaken interactive auth. Give the pipeline its own
**least-privilege service account**, and keep your human account's full SSO and
2FA untouched.

- Create a dedicated service account named for the job; grant it **only** the
  roles it actually calls, one per capability. If it reads one secret and
  deploys one service, it needs exactly those roles and no project-wide admin.
- **Isolate its credentials in a job-owned CLI config** so a scheduled run never
  clobbers (or depends on) your interactive login:

  ```bash
  export CLOUDSDK_CONFIG="$HOME/.config/<cli>-<job>"   # a config dir per job
  # ... the job authenticates non-interactively inside this dir ...
  ```

> **gcloud-specific gotcha.** `GOOGLE_APPLICATION_CREDENTIALS` is honored by
> Google **client libraries / ADC**, but the `gcloud` **CLI itself ignores it**.
> For `gcloud`, authenticate the key explicitly:
> ```bash
> CLOUDSDK_CONFIG="$HOME/.config/gcloud-<job>" \
>   gcloud auth activate-service-account --key-file=<keyfile>
> ```
> Setting only `GOOGLE_APPLICATION_CREDENTIALS` silently leaves `gcloud` on your
> user identity, so the job either uses the wrong account or fails when your
> token expires.

The key file is itself a secret: store it in the vault with `0600` permissions,
never in the repo, a committed dotfile, `argv`, history, or any model context.
See [`SECURE-REMOTE-ACCESS.md`](SECURE-REMOTE-ACCESS.md) section 4 for the full
service-account pattern, and `secret_vault` for storing the key redundantly.

## 6. On-the-go reauth from a phone, over SSH

When you do have to complete an interactive login on a headless or remote box,
you do not need to forward a browser or hand anyone a one-time code. Use the
"paste the code back" flow, where the second factor never leaves the device in
your hand:

```bash
# SSH into the box (ideally over a private tailnet), then:
<cloud-cli> auth login --no-launch-browser
# it prints a URL. Open the URL in the browser on YOUR phone or laptop,
# complete 2FA there, and paste the short verification code back into the
# SSH session.
```

The verification code is single-use and only means anything to the session that
printed the URL. No standing credential, password, or TOTP seed ever enters a
config file, a chat, or the model. Full treatment, including keeping that SSH
path private, is in [`SECURE-REMOTE-ACCESS.md`](SECURE-REMOTE-ACCESS.md)
section 3.

## Checklist

- [ ] The value crosses exactly one anonymous pipe from vault to consumer.
- [ ] Nothing prints the value. Only a fingerprint, a length, or a status is ever
      shown or returned.
- [ ] No secret in `argv`, an env var that outlives the process, a committed
      file, a log, a URL, a screenshot, or the model's context.
- [ ] A brand-new secret was seeded by a human once (pattern 3); everything after
      is autonomous.
- [ ] Any pipe that touches a real secret was dry-run with a **dummy** first.
- [ ] Unattended jobs use a least-privilege service account in a job-owned config,
      not your interactive login.
- [ ] Anything that ever touched a forbidden surface is treated as compromised and
      rotated, not "un-leaked".
