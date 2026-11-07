# `packaged_app_identity` add-on (contributor notes)

A default-off, stack-neutral add-on that captures two macOS / Electron packaging
failures which masquerade as application bugs: a signed bundle missing the Apple
Events automation entitlement (or its Info.plist usage description), and a stale
prior executable being reactivated so the *visible* build is not the *installed*
build.

It stamps `tools/packaged_app_identity/` (a stdlib-only `verify.py` plus a
host-only `acceptance.sh`) and `docs/PACKAGED_APP_IDENTITY.md`.

Enable it while stamping:

```bash
./bin/firestart.sh --defaults --set include_packaged_app_identity=yes
```

Everything here is **observe / plan only**: it reads inputs and prints a verdict
or a non-executing plan. Nothing launches, installs, signals, or terminates a
process. `verify.py` shells out to nothing and runs on any platform;
`acceptance.sh` is the single host-only step (`codesign` against a signed
`.app`) and skips cleanly off macOS.

Contract tests use synthetic property lists, a synthetic `.app` tree, and fake
`uname` / `codesign` executables on `PATH`, so the macOS branch of the
acceptance check is exercised hermetically on Linux CI without a real bundle.
The verdict logic (entitlement, usage description, running-vs-installed
identity, single-instance-lock staleness, exact-pid stop plan) is covered
directly, and a source scan proves the stop planner never reaches for a
process-name kill.
