#!/usr/bin/env bash
# Open one scoped, tailnet-only, key-authenticated SSH channel on this Linux host.
# Usage: ./linux.sh "ssh-ed25519 AAAA... agent@other-host"
set -euo pipefail

KEY="${1:-}"
[ -n "$KEY" ] || { echo "usage: $0 '<public key>'" >&2; exit 1; }
ok()   { printf '  [ok]   %s\n' "$1"; }
warn() { printf '  [warn] %s\n' "$1"; }
head_() { printf '\n== %s\n' "$1"; }

head_ "sshd"
if ! command -v sshd >/dev/null 2>&1; then
  echo "  installing openssh-server"
  if   command -v apt-get >/dev/null; then sudo apt-get update -qq && sudo apt-get install -y openssh-server
  elif command -v dnf     >/dev/null; then sudo dnf install -y openssh-server
  elif command -v pacman  >/dev/null; then sudo pacman -S --noconfirm openssh
  else warn "unknown package manager; install openssh-server yourself"; fi
fi
sudo systemctl enable --now sshd 2>/dev/null || sudo systemctl enable --now ssh
ok "sshd enabled and running"

head_ "Authorized key"
mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
grep -qF "$KEY" ~/.ssh/authorized_keys || printf '%s\n' "$KEY" >> ~/.ssh/authorized_keys
ok "key present"

head_ "Password authentication"
D=/etc/ssh/sshd_config.d/10-agent-host.conf
sudo mkdir -p "$(dirname "$D")"
printf 'PasswordAuthentication no\nPubkeyAuthentication yes\n' | sudo tee "$D" >/dev/null
sudo systemctl reload sshd 2>/dev/null || sudo systemctl reload ssh
ok "password auth disabled via $D"

head_ "Firewall"
if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -qi active; then
  if ip=$(tailscale ip -4 2>/dev/null | head -1) && [ -n "$ip" ]; then
    sudo ufw allow in on tailscale0 to any port 22 proto tcp >/dev/null 2>&1 || \
      warn "could not scope ufw to tailscale0; check manually"
    ok "ufw allows 22 on tailscale0 only"
  fi
else
  warn "no active ufw; port 22 exposure depends on your existing firewall"
fi

head_ "Reachability"
ip="$(tailscale ip -4 2>/dev/null | head -1 || true)"
[ -n "$ip" ] && ok "tailnet address $ip" || warn "tailscale ip returned nothing"

echo
echo "Revoke with: sudo systemctl disable --now sshd; sudo rm -f $D"
echo "and drop the agent-host line from ~/.ssh/authorized_keys"
