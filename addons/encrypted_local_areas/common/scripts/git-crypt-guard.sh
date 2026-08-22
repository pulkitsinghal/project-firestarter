#!/usr/bin/env bash
# git-crypt-guard.sh — fail-closed pre-commit guard for encrypted local areas.
#
# Refuses to commit PLAINTEXT into a git-crypt-encrypted area. This is the safety
# net for the classic footgun: you cloned {{ project_name }} but never ran
# `git-crypt unlock` (the key lives in {{ password_manager }} + the OS keychain),
# so git-crypt's clean filter is NOT active and a file added under an encrypted
# path would be committed IN THE CLEAR. This guard catches that before it happens.
#
# How it works: for every staged file that .gitattributes marks
# `filter=git-crypt`, it reads the STAGED blob's first 10 bytes. git-crypt
# prefixes every encrypted blob with the magic preamble `\0GITCRYPT\0`
# (hex 00 47 49 54 43 52 59 50 54 00). If a guarded file's staged bytes are NOT
# that header, the file is plaintext → fail closed and block the commit.
# git-crypt stores its runtime key below `git rev-parse --git-dir`, which is a
# per-worktree gitdir for linked worktrees. Keys do not inherit from an unlocked
# main checkout, and removing a worktree removes any key installed there. See
# docs/ENCRYPTED_LOCAL_AREAS.md before using git-crypt in a linked worktree.
#
# It is pure `git` plumbing: it needs the real index + working tree (so it runs
# on the HOST, not in Docker) but needs no git-crypt binary — so it still fires
# on a machine where git-crypt was never installed. Bypass (danger):
# `git commit --no-verify`. Runbook: docs/ENCRYPTED_LOCAL_AREAS.md.

set -uo pipefail

# git-crypt's 10-byte encrypted-blob preamble, as normalized `od -tx1` hex.
GITCRYPT_MAGIC_HEX="00 47 49 54 43 52 59 50 54 00"
GITCRYPT_KEY_MAGIC_HEX="00 47 49 54 43 52 59 50 54 4b 45 59 00"

crypt_status() {
  encrypted=()
  while IFS= read -r -d '' path; do
    attr="$(git check-attr filter -- "$path" 2>/dev/null | sed 's/.*: //')"
    [ "$attr" = "git-crypt" ] && encrypted+=("$path")
  done < <(git ls-files -z)

  if [ "${#encrypted[@]}" -eq 0 ]; then
    echo "? git-crypt status unknown: no encrypted tracked file can prove this checkout is unlocked." >&2
    return 2
  fi

  gitdir="$(git rev-parse --absolute-git-dir 2>/dev/null)" || {
    echo "? git-crypt status unknown: cannot resolve this checkout's gitdir." >&2
    return 2
  }
  key_path="$gitdir/git-crypt/keys/default"
  if [ ! -f "$key_path" ]; then
    echo "✗ git-crypt LOCKED: this checkout has no default key in its own gitdir." >&2
    return 1
  fi
  key_hdr="$(od -An -v -tx1 -N13 -- "$key_path" 2>/dev/null \
        | tr '\n' ' ' | tr -s ' ' | sed -e 's/^ *//' -e 's/ *$//')" || true
  if [ "$key_hdr" != "$GITCRYPT_KEY_MAGIC_HEX" ]; then
    echo "? git-crypt status unknown: the worktree-local default key is invalid." >&2
    return 2
  fi

  locked=0
  unreadable=0
  for path in "${encrypted[@]}"; do
    if [ ! -f "$path" ]; then
      unreadable=$((unreadable + 1))
      continue
    fi
    hdr="$(od -An -v -tx1 -N10 -- "$path" 2>/dev/null \
          | tr '\n' ' ' | tr -s ' ' | sed -e 's/^ *//' -e 's/ *$//')" || true
    [ "$hdr" = "$GITCRYPT_MAGIC_HEX" ] && locked=$((locked + 1))
  done

  if [ "$locked" -ne 0 ]; then
    echo "✗ git-crypt LOCKED: $locked encrypted tracked file(s) still contain ciphertext." >&2
    return 1
  fi
  if [ "$unreadable" -ne 0 ]; then
    echo "? git-crypt status unknown: $unreadable encrypted tracked file(s) are absent or unreadable." >&2
    return 2
  fi
  echo "✓ git-crypt UNLOCKED: ${#encrypted[@]} encrypted tracked file(s) are readable plaintext."
}

if [ "${1:-}" = "--status" ]; then
  [ "$#" -eq 1 ] || { echo "usage: $0 [--status]" >&2; exit 2; }
  crypt_status
  exit $?
elif [ "$#" -ne 0 ]; then
  echo "usage: $0 [--status]" >&2
  exit 2
fi

fail=0
bad=""

# Staged additions/copies/modifications/renames, NUL-delimited (odd names safe).
while IFS= read -r -d '' path; do
  # Does git-crypt's clean filter apply to this path, per .gitattributes?
  # (`git check-attr` reads .gitattributes even when the filter isn't configured
  # in .git/config — which is exactly the unlocked-vs-not situation we guard.)
  attr="$(git check-attr filter -- "$path" 2>/dev/null | sed 's/.*: //')"
  [ "$attr" = "git-crypt" ] || continue

  # First 10 bytes of the STAGED blob (":path" = the index copy = what commits).
  hdr="$(git cat-file blob ":$path" 2>/dev/null \
        | od -An -v -tx1 -N10 2>/dev/null \
        | tr '\n' ' ' | tr -s ' ' | sed -e 's/^ *//' -e 's/ *$//')" || true

  if [ "$hdr" != "$GITCRYPT_MAGIC_HEX" ]; then
    bad="$bad  $path"$'\n'
    fail=1
  fi
done < <(git diff --cached --name-only -z --diff-filter=ACMR)

if [ "$fail" -ne 0 ]; then
  {
    echo "✗ pre-commit: refusing to commit PLAINTEXT into an encrypted area."
    echo ""
    echo "These staged files live under a git-crypt path but are NOT encrypted:"
    printf '%s' "$bad"
    echo "The git-crypt key is not active in this checkout, so data that must be"
    echo "encrypted at rest would be committed in the clear."
    echo ""
    echo "Fix — unlock the repo, then re-stage:"
    echo "    git-crypt unlock          # key from {{ password_manager }} + OS keychain"
    echo "    git add <files> && git commit"
    echo ""
    echo "Runbook: docs/ENCRYPTED_LOCAL_AREAS.md. Override (danger): git commit --no-verify."
  } >&2
  exit 1
fi

exit 0
