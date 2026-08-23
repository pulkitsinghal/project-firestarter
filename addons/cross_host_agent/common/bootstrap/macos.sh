#!/usr/bin/env bash
# Open one scoped, tailnet-only, key-authenticated SSH channel on this Mac.
#
# macOS has Remote Login built in, so this is mostly about narrowing it rather than
# installing anything: key-only, and reachable on the tailnet rather than every network
# the laptop ever joins.
#
# Usage: ./macos.sh "ssh-ed25519 AAAA... agent@other-host"
set -euo pipefail

KEY="${1:-}"
[ -n "$KEY" ] || { echo "usage: $0 '<public key>'" >&2; exit 1; }

ok()   { printf '  [ok]   %s\n' "$1"; }
warn() { printf '  [warn] %s\n' "$1"; }
head_() { printf '\n== %s\n' "$1"; }

head_ "Remote Login"
if systemsetup -getremotelogin 2>/dev/null | grep -qi 'on'; then
  ok "already enabled"
else
  echo "  enabling (needs sudo)"
  sudo systemsetup -setremotelogin on
  ok "enabled"
fi

head_ "Authorized key"
mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
if grep -qF "$KEY" ~/.ssh/authorized_keys; then
  ok "key already present"
else
  printf '%s\n' "$KEY" >> ~/.ssh/authorized_keys
  ok "key added"
fi

head_ "Password authentication"
# Leave the system config alone if another service depends on it; report rather than
# silently reconfigure a machine someone else also uses.
if sudo grep -qE '^\s*PasswordAuthentication\s+no' /etc/ssh/sshd_config 2>/dev/null; then
  ok "already disabled"
else
  warn "password auth is still enabled in /etc/ssh/sshd_config"
  warn "set 'PasswordAuthentication no' there if this host is agent-facing only"
fi

head_ "Reachability"
if command -v tailscale >/dev/null 2>&1; then
  ip="$(tailscale ip -4 2>/dev/null | head -1 || true)"
  if [ -n "$ip" ]; then
    if nc -z -G 5 "$ip" 22 2>/dev/null; then ok "reachable on the tailnet at $ip"
    else warn "NOT reachable at $ip; check the macOS firewall"; fi
  else warn "tailscale ip returned nothing"; fi
else
  warn "tailscale not installed; this host will only be reachable on its LAN"
fi

cat <<'EOF'

macOS has no per-interface firewall rule to scope this the way Windows does. If this host
should only be reachable over the tailnet, either bind sshd to the tailnet address in
/etc/ssh/sshd_config with ListenAddress, or leave the application firewall on and allow
only sshd. Revoke by dropping the key line and running:

  sudo systemsetup -setremotelogin off
EOF
