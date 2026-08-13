#!/usr/bin/env bash
# Mutation proof: every crypto guarantee is load-bearing. For each mutation we
# break one behavior, prove a NAMED property test turns red, then restore the
# source byte-identically (sha256 verified). Restore is cp-from-copy, never a
# VCS checkout.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python

fail=0
mutate() {  # <file> <perl-expr> <target-test> <label>
  local file="$1" expr="$2" test="$3" label="$4" before after
  before="$(shasum -a 256 "$file" | awk '{print $1}')"
  cp "$file" "$file.bak"
  perl -0pi -e "$expr" "$file"
  if [ "$(shasum -a 256 "$file" | awk '{print $1}')" = "$before" ]; then
    echo "  ✗ $label — mutation did not change the file (pattern drift)"; fail=1
    rm -f "$file.bak"; return
  fi
  if $PY -m pytest -q -k "$test" tests/test_properties.py tests/test_vectors.py >/dev/null 2>&1; then
    echo "  ✗ $label — '$test' still PASSED under mutation (guarantee not load-bearing!)"; fail=1
  else
    echo "  ✓ $label — '$test' correctly died"
  fi
  cp "$file.bak" "$file"; rm -f "$file.bak"
  after="$(shasum -a 256 "$file" | awk '{print $1}')"
  [ "$before" = "$after" ] || { echo "  ✗ $label — restore not byte-identical"; fail=1; }
}

echo "mutation proofs:"
mutate notebook_crypto/primitives.py \
  's/ciphertext = AESGCM\(key\)\.encrypt\(nonce, plaintext, aad\)/ciphertext = plaintext/' \
  test_sealed_bytes_contain_no_plaintext "M1 AEAD no-op → server-blind"
mutate notebook_crypto/envelope.py \
  's/ikm=_lp\(user_share\) \+ _lp\(system_share\), salt=_KEK_SALT/ikm=_lp(user_share), salt=_KEK_SALT/' \
  test_open_fails_with_only_user_share "M2 KEK ignores system share → dual-key"
mutate notebook_crypto/blind_index.py \
  's/return P\.hkdf_sha256\(ikm=_lp\(user_share\) \+ _lp\(system_share\), salt=_BI_SALT, info=_BI_INFO\)/return b"\\x00" * 32/' \
  test_same_name_across_users_yields_different_index "M3 constant blind-index key → per-user isolation"
mutate notebook_crypto/envelope.py \
  's/_lp\(self\.field\) \+ _lp\(self\.row_id\) \+ _lp\(self\.version\)/_lp(self.field) + _lp(self.version)/' \
  test_ciphertext_cannot_be_substituted_into_another_row "M4 AAD drops row id → substitution"
mutate notebook_crypto/envelope.py \
  's/if not isinstance\(value, \(bytes, bytearray\)\) or len\(value\) != P\.KEY_LEN:/if False:/' \
  test_derive_kek_rejects_empty_shares "M5 share validation off → fail-open"
mutate notebook_crypto/blind_index.py \
  's/t = unicodedata\.normalize\("NFKC", text\)/t = text/' \
  test_canonicalization_folds_unicode_variants "M6 NFKC dropped → dedup fragments"
mutate notebook_crypto/blind_index.py \
  's/ikm=_lp\(user_share\) \+ _lp\(system_share\), salt=_BI_SALT/ikm=_lp(user_share), salt=_BI_SALT/' \
  test_blind_index_key_vector "M7 blind-index single-share → KAT vector"
mutate notebook_crypto/envelope.py \
  's/_lp\(layer\) \+ _lp\(self\.tenant\) \+ _lp\(self\.field\)/_lp(layer) + _lp(self.field)/' \
  test_ciphertext_cannot_be_substituted_across_tenants "M8 AAD drops tenant → cross-notebook substitution"
mutate notebook_crypto/envelope.py \
  's/_lp\(self\.tenant\) \+ _lp\(self\.field\) \+ _lp\(self\.row_id\)/_lp(self.tenant) + _lp(self.row_id)/' \
  test_ciphertext_cannot_be_moved_between_fields "M9 AAD drops field → cross-field substitution"
mutate notebook_crypto/envelope.py \
  's/_lp\(self\.row_id\) \+ _lp\(self\.version\)/_lp(self.row_id)/' \
  test_ciphertext_cannot_be_rolled_back_to_an_old_version "M10 AAD drops version → rollback"
mutate notebook_crypto/envelope.py \
  's/return _lp\(layer\) \+ _lp\(self\.tenant\)/return _lp(self.tenant)/' \
  test_aad_wire_format_vector "M11 AAD drops layer label → wire-format vector"

echo
if [ "$fail" = 0 ]; then echo "ALL MUTATIONS KILLED ✓"; else echo "MUTATION CHECK FAILED ✗"; fi
exit $fail
