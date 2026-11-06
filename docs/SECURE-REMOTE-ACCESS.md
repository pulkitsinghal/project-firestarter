# Secure remote access + owner-controlled auth for your dev machines

A companion to [docs/REMOTE-ACCESS.md](REMOTE-ACCESS.md). That doc exposes a
stamped project's local service so you can reach it from anywhere, privately.
This one hardens the **machine** that hosts it: how to keep remote shell access
private, how to keep sign-in (SSO, 2FA, OTP) in your own hands, and how to let
unattended automation keep running without weakening either.

Everything here is a reusable pattern. Substitute your own host, tailnet, and
project names for the `<placeholders>`. Nothing in this doc should contain a real
hostname, address, account, or key path, by design: the whole point is that your
real attack surface is not written down in a public repo.

## The principle: a private mesh, not a public port

The default posture for a developer machine is **no service on a public port and
no shell on a public port**. Instead, put every device you own on one private
WireGuard mesh (Tailscale) and reach them by their stable `*.ts.net` names. A
peer that is not on your tailnet cannot see the ports at all, which is strictly
more private than a public tunnel plus a password.

Decision order for *any* inbound path (shell or service):

1. **Same LAN only** -> bind to loopback or the LAN address behind the local firewall.
2. **Your own devices, anywhere, private** -> the tailnet (this doc). Default for anything sensitive.
3. **Strangers, public internet** -> a public tunnel (`tailscale funnel`, Cloudflare Tunnel). Never for a shell, never for private data.

## 1. Tailnet-only access

Install Tailscale on every device (the desktop app on a GUI machine, so MagicDNS
wires into the OS resolver and the node is boot-persistent). Then:

- **Dev servers** go out over the tailnet with HTTPS, not a raw port:
  ```bash
  tailscale serve --bg --https=443 http://127.0.0.1:<port>
  # -> https://<node>.<tailnet>.ts.net/   (tailnet only)
  ```
  Confirm the mode is "tailnet only" and never "funnel" for anything private:
  ```bash
  tailscale serve status      # every line should read "(tailnet only)"
  tailscale funnel status     # should be empty for a private machine
  ```
- **SSH** rides the same mesh. You reach the box at `<node>.<tailnet>.ts.net`
  from your phone or laptop once both are signed into the same tailnet. There is
  no need to expose port 22 to the LAN or the internet.
- Consider **Tailscale ACLs** that allow SSH only from the devices that need it,
  and `ShieldsUp` on a node that should accept no inbound tailnet connections at
  all.

> Tailscale is an extra network interface, not an OS-level firewall. Putting a
> service "on the tailnet" does **not** by itself stop the OS from also listening
> on the LAN or a forwarded public port. Privacy still depends on the two steps
> below (bind/scope the listener) plus your router not forwarding the port.

## 2. SSH hardening: make it key-only

A key-only daemon cannot be brute-forced with a password, which removes the
entire class of credential-stuffing attacks even if the port is somehow reached.
Drop a hardening file so an OS upgrade that rewrites the main config cannot undo
it:

```bash
# /etc/ssh/sshd_config.d/10-hardening.conf   (owner edits this; root-owned)
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no      # deprecated alias; set it anyway
PermitRootLogin prohibit-password       # root may use a key, never a password
AuthenticationMethods publickey
```

Verify the live posture (read-only, safe to run anytime):

```bash
# what the daemon will actually use, merged includes and all:
sshd -T 2>/dev/null | grep -Ei 'passwordauthentication|kbdinteractive|challengeresponse|permitrootlogin'
# the drop-in files themselves:
grep -RiE 'password|kbdinteractive|permitroot' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ 2>/dev/null
```

If every value above is `no` (and root is `prohibit-password` or `no`), the
daemon is key-only.

**Scope the listener.** By default `sshd` binds every interface (`0.0.0.0:22`
and `[::]:22`). Two ways to keep it off the public internet, best used together:

- Bind it to the tailnet address only, so the LAN and WAN never see it:
  ```bash
  # /etc/ssh/sshd_config.d/10-hardening.conf
  ListenAddress <your-tailnet-ip>
  ```
- Confirm the router/NAT forwards **no** port to 22. From off-network, a
  connection to your public IP on 22 must time out. Check what is listening and
  on which addresses:
  ```bash
  # macOS / BSD:
  netstat -an -p tcp | grep -E '\.22 .*LISTEN'
  # Linux:
  ss -ltnp 'sport = :22'
  ```
  A bind of `*:22` plus a router that forwards 22 is the one combination to
  avoid. Key-only auth makes a password attack futile, but an open public port
  is still noise, fingerprinting, and future-CVE exposure you do not need.

## 3. Keep SSO / 2FA / OTP in your own hands

When a cloud CLI token expires you often have to complete an interactive,
browser-plus-2FA sign-in. You do not need to forward a browser or hand anyone a
one-time code to do that on a headless or remote box. Use the "paste the code
back" flow, where the second factor never leaves the device in your hand:

```bash
# SSH into the box over the tailnet from your phone or laptop, then:
<cloud-cli> auth login --no-launch-browser
<cloud-cli> auth application-default login --no-launch-browser
# each prints a URL. Open it in the browser on YOUR device, complete 2FA there,
# and paste the short verification code back into the SSH session.
```

The verification code is single-use and only means anything to the session that
printed the URL. You complete every OTP and push prompt on your own phone. This
is how you reauth from anywhere without putting a standing credential, a
password, or a TOTP seed into the model, a config file, or a chat.

## 4. Least-privilege service account for unattended automation

Interactive SSO is right for a human at a keyboard and wrong for a `launchd` /
`systemd` / cron pipeline, which will eventually fire while your user token is
expired and fail. The fix is **not** to loosen interactive auth. It is to give
only the non-interactive pipeline its own **least-privilege service account**,
while your own account keeps full SSO and 2FA.

Pattern:

1. Create a dedicated service account for the automation, named for its job.
2. Grant it **only** the roles the pipeline actually calls, one per capability.
   Resist a broad role; if the pipeline reads one secret and deploys one service,
   it needs exactly those two or three roles and no project-wide admin.
   ```bash
   <cloud-cli> iam service-accounts create automation --project <project>
   <cloud-cli> <project> add-iam-policy-binding \
     --member="serviceAccount:automation@<project>.iam.gserviceaccount.com" \
     --role="roles/<one-capability-the-pipeline-needs>"    # repeat per capability
   ```
3. Issue it a key file and lock the permissions:
   ```bash
   <cloud-cli> iam service-accounts keys create <keyfile>.json \
     --iam-account=automation@<project>.iam.gserviceaccount.com
   chmod 600 <keyfile>.json
   ```
4. Have the pipeline consume the key non-interactively, either by pointing the
   SDK at it (`GOOGLE_APPLICATION_CREDENTIALS=<keyfile>` for Google SDKs) or by
   activating it for a scoped block of commands and then restoring your user
   account afterward.

**The key is a secret: it belongs in a vault, not in the repo, a dotfile you
commit, argv, shell history, or any AI context.** Do not restate secret handling
here. Use the vault add-ons:

- [`secret_vault`](../addons/secret_vault/README.md) for redundant, fingerprinted
  storage and runtime injection (`secret-get --exec` streams the value straight
  into the consumer and never echoes it).
- The private overlay's `secret_injection` add-on for the vault-to-server pipe
  (seed once by a human, then stream the value from the secret manager into the
  target over a pipe; it never lands in a committed file or the model).

The owner still owns the pipeline and the vault. The service account only lets
the pipeline keep running across your SSO expiry; it is not a second way in for a
person.

## 5. Machine hardening checklist (read-only audit)

Run these to confirm a machine's posture without changing anything. Treat every
"fix" as owner-gated: recommend, then let the owner apply it.

| Check | Command (macOS) | Want |
|-------|-----------------|------|
| SSH key-only | `sshd -T \| grep -i passwordauthentication` | `no` |
| Port 22 scope | `netstat -an -p tcp \| grep '\.22 .*LISTEN'` | tailnet address, or `*` only behind a no-forward router |
| Remote Login state | `sudo systemsetup -getremotelogin` | On only if you use SSH; off otherwise |
| Tailnet serve mode | `tailscale serve status` / `tailscale funnel status` | serve "tailnet only"; funnel empty |
| Application firewall | `/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate` | enabled (+ stealth mode on) |
| Disk encryption | `fdesetup status` | FileVault On |
| Auto-login | `defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser` | key absent (off) |
| Screen lock | System Settings > Lock Screen | require password immediately |
| Guest account | `defaults read /Library/Preferences/com.apple.loginwindow GuestEnabled` | `0` |

On Linux substitute `ss -ltnp`, `ufw status` / `firewalld`, `cryptsetup status`
for the root device, and your display manager's lock policy. On Windows audit
RDP exposure, Network Level Authentication, an account-lockout policy, BitLocker,
and that the only inbound path is the tailnet.

The single most important line is the first one. If SSH password authentication
is **on** and port 22 is reachable from beyond your tailnet, fix that before
anything else.
