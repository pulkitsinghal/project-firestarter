# `trusted_workstation` add-on (contributor notes)

This default-off, stack-neutral add-on defines the read-only first phase of a
trusted-workstation enrollment flow. It stamps a machine-readable policy and
ledger schema plus macOS shell and Windows PowerShell doctor/status tools.

Phase 1 deliberately cannot enroll a machine. The scripts do not retrieve
secrets, call Tailscale, configure Git, install hooks, mutate services or
firewalls, create Mutagen sessions, or write a ledger. They inspect the current
clone, discover whether required command names exist, and read a ledger only
when the operator supplies one or one already exists at the documented path.

Contract tests use synthetic repositories, fake executables, malformed ledgers,
linked Git metadata, and source scans for forbidden mutating command forms.
