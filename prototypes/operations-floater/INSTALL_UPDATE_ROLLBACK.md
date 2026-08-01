# Install, update, and rollback plan

Operations Floater has no network updater. Application replacement and snapshot
updates are explicit local operations with a retained rollback artifact.
The concise architecture contract is also recorded in
[`docs/PERMISSION_AND_INSTALL_LIFECYCLE.md`](docs/PERMISSION_AND_INSTALL_LIFECYCLE.md).

## Permission-bearing identity

Microphone and Speech Recognition are privacy-protected
resources associated with the app's macOS code identity. Apple documents that
macOS records a signed app's designated requirement (DR) and uses it to
recognize later versions. An unsigned app has no DR; an ad-hoc signed app's DR
is tied to that exact code version. Routine unsigned or ad-hoc builds therefore
must remain disposable and must never replace or launch as the installed,
permission-bearing app.

The release app must keep all of these stable:

- one owner-controlled bundle identifier, supplied outside Git;
- one Developer ID team and the Xcode-produced designated requirement;
- one installed path, normally `/Applications/Operations Floater.app`; and
- one main application process as the microphone and speech-recognition client.

Do not hand-author a custom DR. If a future Mac App Store variant must share
privacy grants with a Developer ID variant, follow Apple's mutually compatible
DR procedure and test both directions before shipping. A change of signing
channel, development certificate, team, or bundle identifier is a permission
migration and must not be presented as a routine update.

References:

- [Apple TN3127: Inside Code Signing — Requirements](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements)
- [Apple: Creating distribution-signed code for macOS](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac)

## Release inputs

Keep these outside Git and set them to operator-controlled locations:

```bash
CANDIDATE_APP=...
INSTALLED_APP=...
BACKUP_APP=...
OPERATIONS_FLOATER_BUNDLE_ID=...
OPERATIONS_FLOATER_TEAM_ID=...
```

The candidate must be produced from the reviewed Firestarter commit with the
owner's bundle identifier and signing configuration. Do not place certificates,
profiles, account identifiers, runtime snapshots, or application backups in this
repository.

The checked-in `com.example.operationsfloater` identifier is only for unsigned,
disposable builds. A release archive must override it with the stable value.

Operations Floater currently has no login item, launch agent, daemon, privileged
helper, or updater. Do not add one to work around TCC. If a future helper is
actually needed, it must live inside the signed app bundle, use its own unique
code-signing identifier, and follow `SMAppService`; that is a separate design
and owner gate.

An old helper from an unrelated or experimental build is not removed
automatically. Inspecting or removing one is separate owner-controlled
maintenance; the current app works with no helper.

## Preflight

Before replacing an installed copy:

1. Record the candidate commit, bundle version, and short version.
2. Verify the signature and Gatekeeper assessment:

   ```bash
   codesign --verify --deep --strict --verbose=2 "$CANDIDATE_APP"
   spctl --assess --type execute --verbose=2 "$CANDIDATE_APP"
   ```

3. For an update, prove that the installed app and candidate have mutually
   compatible DRs and that the build number increases:

   ```bash
   prototypes/operations-floater/scripts/verify-permission-identity.sh \
     --candidate "$CANDIDATE_APP" \
     --installed "$INSTALLED_APP" \
     --expected-bundle-id "$OPERATIONS_FLOATER_BUNDLE_ID" \
     --expected-team-id "$OPERATIONS_FLOATER_TEAM_ID"
   ```

   For a first install, omit `--installed`. The preflight is read-only: it does
   not sign, copy, launch, quit, grant/reset TCC, or open System Settings.
4. Confirm the built metadata contains the Dock icon, productivity category,
   expected encryption declaration, regular app activation, and no unexpected
   embedded helper.
5. Run the native unit/lifecycle tests and synthetic identity-preflight test
   from the same commit. Compile an app bundle only on a disposable macOS
   account or CI runner: Xcode 26.5 runs `lsregister` during both `build` and
   `archive`, and `REGISTER_WITH_LAUNCH_SERVICES=NO` did not suppress it in
   battle testing.
6. Export or retain the current local snapshot only in its private local
   storage. Never copy it into Git or a web publication directory.

Stop if identity, signature, metadata, or tests do not match the intended
release.

## First install

1. Quit any running copy.
2. Copy the candidate to `INSTALLED_APP` using a metadata-preserving local copy.
3. Launch only the installed path. Grant Microphone and Speech Recognition once
   when the app explicitly asks, if the user approves. Never grant permission to
   a DerivedData product, SwiftPM executable, or disposable copy.
4. Verify one visible dashboard window and one app process, default frontmost state,
   unpin behavior, Command-W close, Dock reopen, and Reduce Motion.
   At the default size, confirm queue and supporting panels use two columns.
   Resize to the minimum and confirm they collapse to one column without
   clipping the guide summary or four queue counters.
5. Confirm each queue race shows a bounded progress chip, hover detail, and
   click-to-expand detail. Exercise last-active, completion, memory, CPU, and
   needs-attention sorting. Confirm an increased total-step count can move a
   chip backward and Reduce Motion replaces animation with a stable frame.
6. Confirm assistant chat initially reports **OFF** and performs no availability
   probe. Enable it explicitly, use only a synthetic prompt, and verify a
   response. Use **Shift-Return** to create a two-line draft and confirm it
   remains unsent; then press **Return** and confirm one two-line message is
   submitted and the composer clears. Turn on **Review replies** or click
   **Review** and confirm **CHECKING** becomes **CHECKED** or an actionable
   **IMPROVE** card. Stop if the client contacts anything other than
   `127.0.0.1:11500`, follows a redirect, or silently sends dashboard state.
7. Choose **Import Local Snapshot…** only if a canonical `local` version `1.0`
   snapshot is ready. The app validates before writing and gives the stored file
   private permissions.
8. Confirm the header reports a locally verified snapshot rather than the
   generic sample.

## Update

1. Complete the preflight for the new candidate.
2. Quit the installed app.
3. Copy the existing installed app to `BACKUP_APP`.
4. Replace `INSTALLED_APP` with the candidate using a metadata-preserving copy.
5. Launch only the stable installed path and repeat the lifecycle smoke checks.
   Do not remove/re-add the microphone or speech-recognition grants. If preflight
   passed but the existing grant is not recognized, stop and restore the backup;
   do not mutate TCC as a troubleshooting shortcut.
6. Press **Give floor** and start Voice Conversation. It must reach floor
   granted + listening together. Denied Microphone or Speech Recognition, or a
   failed audio startup, must leave the floor revoked and voice off with an
   actionable error.
7. Import the new local snapshot, if needed. A valid current snapshot is saved
   as the previous snapshot before the update is committed.
8. Leave `BACKUP_APP` and the previous snapshot intact through the acceptance
   period.

An invalid snapshot cannot replace the active snapshot. No selected source path
is retained, and no import data is transmitted.

## Rollback

Rollback triggers include failure to launch, signature or Gatekeeper rejection,
missing window lifecycle behavior, an unreadable compact layout, motion that
continues with Reduce Motion enabled, unreadable canonical state, chat egress
beyond the fixed loopback Router, loss of a prior microphone or speech-recognition
grant despite mutually compatible DRs, a duplicate app process, voice that fails
to stop cleanly after a failed startup, or a material display regression.

1. Quit the app.
2. Replace `INSTALLED_APP` with the verified `BACKUP_APP`.
3. Launch the restored app and verify its bundle version and lifecycle.
4. If only dashboard data regressed, choose **Restore Previous Snapshot**. The
   app validates the previous snapshot and swaps it with the current one, making
   the rollback itself reversible.
5. Re-run the focused native tests against the restored commit.

Do not delete the candidate, backup, or previous snapshot until the restored
state has passed the same acceptance checks.

Do not run `tccutil reset`, remove/re-add the app in System Settings, or alter
the TCC database during rollback. Those actions destroy the evidence needed to
distinguish an identity regression from a permission-state problem.

## Cleanup

After acceptance:

- keep only the retention-approved application backup;
- remove rejected snapshot source files through the operator's normal secure
  local cleanup process;
- retain release commit, test output, and non-sensitive metadata as evidence;
  and
- never include runtime snapshot contents in bug reports or release notes.
